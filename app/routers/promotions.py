"""Khuyến mãi (UC-18, UC-21): phần trăm hoặc số tiền, theo sản phẩm, nhóm hàng hoặc toàn hóa đơn."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Category, Product, Promotion, User, now
from app.schemas import InvoiceIn, PromotionIn, PromotionStatusIn, ValidateCodeIn
from app.security import ALL_STAFF, MANAGERS
from app.services import audit, pricing, sales
from app.services.inventory import BusinessError

router = APIRouter(prefix="/api/promotions", tags=["promotions"])


def promotion_out(db: Session, p: Promotion) -> dict:
    target = None
    if p.scope == "product" and p.target_id:
        prod = db.get(Product, p.target_id)
        target = f"{prod.code} - {prod.name}" if prod else None
    elif p.scope == "category" and p.target_id:
        cat = db.get(Category, p.target_id)
        target = cat.name if cat else None
    t = now()
    running = p.status == "active" and p.start_at <= t <= p.end_at and \
        (p.usage_limit is None or p.used_count < p.usage_limit)
    return {"id": p.id, "code": p.code, "name": p.name, "promo_type": p.promo_type, "scope": p.scope,
            "target_id": p.target_id, "target_name": target, "discount_value": p.discount_value,
            "max_discount": p.max_discount, "min_invoice_amount": p.min_invoice_amount,
            "requires_code": p.requires_code, "usage_limit": p.usage_limit, "used_count": p.used_count,
            "start_at": p.start_at, "end_at": p.end_at, "status": p.status, "running": running}


@router.get("")
def list_promotions(status: str | None = Query(None, pattern="^(active|paused|expired|running)$"),
                    db: Session = Depends(get_db), _: User = Depends(ALL_STAFF)):
    pricing.refresh_expired(db)
    db.commit()
    rows = [promotion_out(db, p) for p in db.scalars(select(Promotion).order_by(Promotion.end_at.desc()))]
    if status == "running":
        return [r for r in rows if r["running"]]
    return [r for r in rows if not status or r["status"] == status]


def _check_target(db: Session, data: PromotionIn) -> None:
    if data.scope == "product" and db.get(Product, data.target_id) is None:
        raise HTTPException(400, "Sản phẩm áp dụng không tồn tại")
    if data.scope == "category" and db.get(Category, data.target_id) is None:
        raise HTTPException(400, "Nhóm hàng áp dụng không tồn tại")


@router.post("", status_code=201)
def create_promotion(data: PromotionIn, db: Session = Depends(get_db), user: User = Depends(MANAGERS)):
    _check_target(db, data)
    p = Promotion(**data.model_dump(), requires_code=bool(data.code), created_by=user.id)
    if p.end_at < now():
        p.status = "expired"
    db.add(p)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(400, "Mã voucher đã tồn tại")
    return promotion_out(db, p)


@router.put("/{promo_id}")
def update_promotion(promo_id: int, data: PromotionIn, db: Session = Depends(get_db), user: User = Depends(MANAGERS)):
    p = db.get(Promotion, promo_id)
    if p is None:
        raise HTTPException(404, "Không tìm thấy khuyến mãi")
    _check_target(db, data)
    before = promotion_out(db, p)
    for k, v in data.model_dump().items():
        setattr(p, k, v)
    p.requires_code = bool(data.code)
    p.status = "expired" if p.end_at < now() else data.status
    audit.log(db, user, "PROMOTION_UPDATE", "promotions", p.id, old=before, new=promotion_out(db, p))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(400, "Mã voucher đã tồn tại")
    return promotion_out(db, p)


@router.put("/{promo_id}/status")
def set_status(promo_id: int, data: PromotionStatusIn, db: Session = Depends(get_db), user: User = Depends(MANAGERS)):
    """FR-PRM-07: tạm dừng, kích hoạt lại."""
    p = db.get(Promotion, promo_id)
    if p is None:
        raise HTTPException(404, "Không tìm thấy khuyến mãi")
    if data.status == "active" and p.end_at < now():
        raise HTTPException(400, "Khuyến mãi đã hết hạn, hãy sửa thời gian kết thúc trước khi kích hoạt lại")
    audit.log(db, user, "PROMOTION_UPDATE", "promotions", p.id, old={"status": p.status}, new={"status": data.status})
    p.status = data.status
    db.commit()
    return promotion_out(db, p)


@router.post("/validate-code")
def validate_code(data: ValidateCodeIn, db: Session = Depends(get_db), user: User = Depends(ALL_STAFF)):
    """Kiểm tra voucher với giỏ hàng hiện tại; trả lý do khi không hợp lệ (FR-PRM-06)."""
    try:
        promo = pricing.find_voucher(db, data.code)
        if not data.items:
            problem = pricing.promo_problem(promo, 10 ** 12, now())
            return {"valid": problem is None, "reason": problem, "promotion": promotion_out(db, promo)}
        cart = sales.preview(db, InvoiceIn(items=data.items, customer_id=data.customer_id, promo_code=data.code), user)
    except (pricing.PricingError, BusinessError) as e:
        db.rollback()
        return {"valid": False, "reason": str(e)}
    db.rollback()
    return {"valid": True, "reason": None, "promotion": promotion_out(db, promo), "cart": cart.summary()}
