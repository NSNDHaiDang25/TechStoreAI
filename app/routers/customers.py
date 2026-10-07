"""Khách hàng (UC-14, UC-15) và điểm tích lũy (UC-17)."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.ai.service import strip_accents
from app.database import get_db
from app.models import PAID_STATES, Customer, CustomerTier, Invoice, User, Warranty, now
from app.routers.invoices import mask_phone
from app.schemas import CustomerIn, CustomerOut, PointsAdjustIn
from app.security import ALL_STAFF, MANAGERS
from app.services import audit, loyalty

router = APIRouter(prefix="/api/customers", tags=["customers"])


def _stats(db: Session, customer_id: int) -> dict:
    count, last = db.execute(
        select(func.count(Invoice.id), func.max(Invoice.paid_at))
        .where(Invoice.customer_id == customer_id, Invoice.status.in_(PAID_STATES))
    ).one()
    return {"invoice_count": count, "last_purchase": last}


def customer_out(db: Session, c: Customer, full_phone: bool) -> dict:
    data = CustomerOut.model_validate(c).model_dump()
    tier = db.get(CustomerTier, c.tier_id) if c.tier_id else None
    data["tier_name"] = tier.name if tier else loyalty.BASE_TIER
    data["points_multiplier"] = tier.points_multiplier if tier else 1.0
    if not full_phone:
        data["phone"] = mask_phone(c.phone)  # BR-40, FR-CUS-05
    return data


@router.get("")
def list_customers(q: str | None = None, group: str | None = None, tier_id: int | None = None,
                   active: bool | None = None, full_phone: bool = False,
                   page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=200),
                   db: Session = Depends(get_db), _: User = Depends(ALL_STAFF)):
    """FR-CUS-03: tìm nhanh theo số điện thoại hoặc tên (không phân biệt dấu). Danh sách che số điện thoại;
    full_phone=true dùng ở ô chọn khách của màn hình bán hàng khi tìm đúng số điện thoại."""
    loyalty.ensure_tiers(db)
    stmt = select(Customer)
    if group:
        stmt = stmt.where(Customer.group == group)
    if tier_id:
        stmt = stmt.where(Customer.tier_id == tier_id)
    if active is not None:
        stmt = stmt.where(Customer.is_active.is_(active))
    stmt = stmt.order_by(Customer.id.desc())
    if q and q.strip():
        key = q.strip()
        digits = key.replace(" ", "").replace(".", "")
        if digits.isdigit():
            rows = db.scalars(stmt.where(or_(Customer.phone.like(f"%{digits}%"), Customer.code.ilike(f"%{key}%")))).all()
        else:
            words = strip_accents(key).split()
            rows = [c for c in db.scalars(stmt)
                    if all(w in strip_accents(f"{c.code} {c.name} {c.email or ''}") for w in words)]
        total = len(rows)
        rows = rows[(page - 1) * size: page * size]
    else:
        total = db.scalar(select(func.count()).select_from(stmt.subquery()))
        rows = db.scalars(stmt.offset((page - 1) * size).limit(size)).all()
    show_full = full_phone and bool(q)
    return {"total": total, "items": [{**customer_out(db, c, show_full), **_stats(db, c.id)} for c in rows]}


def _get(db: Session, customer_id: int) -> Customer:
    c = db.get(Customer, customer_id)
    if c is None:
        raise HTTPException(404, "Không tìm thấy khách hàng")
    return c


@router.get("/{customer_id}")
def get_customer(customer_id: int, db: Session = Depends(get_db), _: User = Depends(ALL_STAFF)):
    """FR-CUS-04: hồ sơ khách gồm lịch sử mua, tổng chi tiêu, điểm và thiết bị đang bảo hành."""
    c = _get(db, customer_id)
    history = db.scalars(select(Invoice).where(Invoice.customer_id == customer_id)
                         .order_by(Invoice.created_at.desc()).limit(50)).all()
    today = now().date()
    warranties = db.scalars(select(Warranty).options(joinedload(Warranty.product), joinedload(Warranty.serial))
                            .where(Warranty.customer_id == customer_id, Warranty.status == "active",
                                   Warranty.end_date >= today).order_by(Warranty.end_date)).all()
    return {**customer_out(db, c, True), **_stats(db, c.id), "invoices": [
        {"id": i.id, "code": i.code, "created_at": i.created_at, "total": i.total, "status": i.status,
         "points_earned": i.points_earned, "points_used": i.points_used,
         "items": ", ".join(f"{it.product.name} x{it.quantity}" for it in i.items)}
        for i in history
    ], "warranties": [{"id": w.id, "product_name": w.product.name, "serial_no": w.serial.serial_no if w.serial else None,
                       "start_date": w.start_date, "end_date": w.end_date} for w in warranties],
        "points_history": loyalty.history(db, c.id, 50)}


@router.get("/{customer_id}/invoices")
def customer_invoices(customer_id: int, db: Session = Depends(get_db), _: User = Depends(ALL_STAFF)):
    _get(db, customer_id)
    rows = db.scalars(select(Invoice).where(Invoice.customer_id == customer_id).order_by(Invoice.created_at.desc()))
    return [{"id": i.id, "code": i.code, "created_at": i.created_at, "total": i.total, "status": i.status}
            for i in rows]


@router.get("/{customer_id}/points")
def customer_points(customer_id: int, db: Session = Depends(get_db), _: User = Depends(ALL_STAFF)):
    """FR-LOY-06: lịch sử biến động điểm."""
    c = _get(db, customer_id)
    return {"balance": c.loyalty_points, "history": loyalty.history(db, c.id, 500)}


@router.post("/{customer_id}/points")
def adjust_points(customer_id: int, data: PointsAdjustIn, db: Session = Depends(get_db),
                  user: User = Depends(MANAGERS)):
    """FR-LOY-05, BR-14: chủ cửa hàng điều chỉnh điểm thủ công, bắt buộc lý do, ghi audit log."""
    c = _get(db, customer_id)
    if c.loyalty_points + data.points < 0:
        raise HTTPException(400, f"Khách chỉ có {c.loyalty_points} điểm, không trừ được {-data.points} điểm")
    before = c.loyalty_points
    loyalty.change_points(db, c, data.points, "adjust", note=data.reason, user=user)
    audit.log(db, user, "POINTS_ADJUST", "customers", c.id, old={"points": before},
              new={"points": c.loyalty_points, "reason": data.reason})
    db.commit()
    return {"balance": c.loyalty_points, "history": loyalty.history(db, c.id, 50)}


def _next_customer_code(db: Session) -> str:
    nums = [int(x[2:]) for x in db.scalars(select(Customer.code).where(Customer.code.like("KH%"))) if x[2:].isdigit()]
    return f"KH{max(nums, default=0) + 1:04d}"


def _check_phone(db: Session, phone: str, customer_id: int | None = None) -> None:
    if db.scalar(select(Customer.id).where(Customer.phone == phone, Customer.id != (customer_id or 0))):
        raise HTTPException(400, "Số điện thoại đã được đăng ký cho khách hàng khác")


@router.post("", status_code=201)
def create_customer(data: CustomerIn, db: Session = Depends(get_db), _: User = Depends(ALL_STAFF)):
    _check_phone(db, data.phone)
    values = data.model_dump(exclude={"is_active"})
    values["code"] = values["code"] or _next_customer_code(db)
    c = Customer(**values, tier_id=loyalty.tier_for(db, 0).id)
    db.add(c)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(400, "Mã khách hàng đã tồn tại")
    return customer_out(db, c, True)


@router.put("/{customer_id}")
def update_customer(customer_id: int, data: CustomerIn, db: Session = Depends(get_db),
                    user: User = Depends(ALL_STAFF)):
    c = _get(db, customer_id)
    _check_phone(db, data.phone, customer_id)
    values = data.model_dump(exclude={"code"} if not data.code else set())
    is_active = values.pop("is_active")
    if is_active is not None and is_active != c.is_active:
        if user.role == "staff":
            raise HTTPException(403, "Chỉ chủ cửa hàng được vô hiệu hóa khách hàng")
        audit.log(db, user, "CUSTOMER_DEACTIVATE" if not is_active else "CUSTOMER_ACTIVATE", "customers", c.id,
                  old={"is_active": c.is_active}, new={"is_active": is_active})
        c.is_active = is_active
    for k, v in values.items():
        setattr(c, k, v)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(400, "Mã khách hàng đã tồn tại")
    return customer_out(db, c, True)


@router.delete("/{customer_id}")
def delete_customer(customer_id: int, db: Session = Depends(get_db), _: User = Depends(MANAGERS)):
    c = _get(db, customer_id)
    if db.scalar(select(func.count(Invoice.id)).where(Invoice.customer_id == customer_id)):
        raise HTTPException(400, "Khách hàng đã có hóa đơn, không thể xóa. Hãy vô hiệu hóa khách hàng")
    db.delete(c)
    db.commit()
    return {"ok": True}
