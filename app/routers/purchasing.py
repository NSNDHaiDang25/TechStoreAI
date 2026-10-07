"""Nhà cung cấp (UC-35) và phiếu nhập hàng (UC-36, UC-37)."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.database import get_db, lock_for_write
from app.models import ImportItem, ImportReceipt, Supplier, User
from app.schemas import CancelIn, PurchaseOrderIn, QuickRestockIn, SupplierIn
from app.security import ALL_STAFF, MANAGERS
from app.services import purchasing, restock
from app.services.inventory import BusinessError
from app.services.reports import parse_range

router = APIRouter(prefix="/api", tags=["purchasing"])


# ---------------------------------------------------------------- Nhà cung cấp
def supplier_out(s: Supplier, stats: dict | None = None) -> dict:
    data = {"id": s.id, "code": s.code, "name": s.name, "contact_name": s.contact_name, "phone": s.phone,
            "email": s.email, "address": s.address, "tax_code": s.tax_code, "status": s.status,
            "created_at": s.created_at}
    return {**data, **(stats or {})}


def _supplier_stats(db: Session) -> dict[int, dict]:
    rows = db.execute(select(ImportReceipt.supplier_id, func.count(ImportReceipt.id), func.sum(ImportReceipt.total),
                             func.max(ImportReceipt.received_at))
                      .where(ImportReceipt.status == "confirmed", ImportReceipt.supplier_id.is_not(None))
                      .group_by(ImportReceipt.supplier_id)).all()
    return {r[0]: {"order_count": r[1], "total_amount": int(r[2] or 0), "last_received_at": r[3]} for r in rows}


@router.get("/suppliers")
def list_suppliers(q: str | None = None, status: str | None = Query(None, pattern="^(active|inactive)$"),
                   db: Session = Depends(get_db), user: User = Depends(ALL_STAFF)):
    stmt = select(Supplier)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Supplier.name.ilike(like), Supplier.code.ilike(like), Supplier.phone.ilike(like)))
    if status:
        stmt = stmt.where(Supplier.status == status)
    stats = _supplier_stats(db) if user.role != "staff" else {}
    empty = {"order_count": 0, "total_amount": 0, "last_received_at": None} if user.role != "staff" else {}
    return [supplier_out(s, stats.get(s.id, empty)) for s in db.scalars(stmt.order_by(Supplier.code))]


@router.get("/suppliers/{supplier_id}")
def get_supplier(supplier_id: int, db: Session = Depends(get_db), user: User = Depends(ALL_STAFF)):
    s = db.get(Supplier, supplier_id)
    if s is None:
        raise HTTPException(404, "Không tìm thấy nhà cung cấp")
    orders = db.scalars(select(ImportReceipt).options(joinedload(ImportReceipt.user), selectinload(ImportReceipt.items))
                        .where(ImportReceipt.supplier_id == supplier_id)
                        .order_by(ImportReceipt.created_at.desc()).limit(100)).unique().all()
    return {**supplier_out(s), "purchase_orders": [po_out(o, user, False) for o in orders]}  # FR-SUP-04


@router.post("/suppliers", status_code=201)
def create_supplier(data: SupplierIn, db: Session = Depends(get_db), _: User = Depends(MANAGERS)):
    s = Supplier(**data.model_dump(exclude={"code"}), code=data.code or purchasing.next_supplier_code(db))
    db.add(s)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(400, "Mã nhà cung cấp đã tồn tại")  # FR-SUP-02
    return supplier_out(s)


@router.put("/suppliers/{supplier_id}")
def update_supplier(supplier_id: int, data: SupplierIn, db: Session = Depends(get_db), _: User = Depends(MANAGERS)):
    s = db.get(Supplier, supplier_id)
    if s is None:
        raise HTTPException(404, "Không tìm thấy nhà cung cấp")
    for k, v in data.model_dump(exclude={"code"} if not data.code else set()).items():
        setattr(s, k, v)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(400, "Mã nhà cung cấp đã tồn tại")
    return supplier_out(s)


@router.delete("/suppliers/{supplier_id}")
def delete_supplier(supplier_id: int, db: Session = Depends(get_db), _: User = Depends(MANAGERS)):
    """FR-SUP-03: nhà cung cấp đã có phiếu nhập thì không xóa, chỉ chuyển sang ngừng hợp tác."""
    s = db.get(Supplier, supplier_id)
    if s is None:
        raise HTTPException(404, "Không tìm thấy nhà cung cấp")
    if db.scalar(select(func.count(ImportReceipt.id)).where(ImportReceipt.supplier_id == supplier_id)):
        s.status = "inactive"
        db.commit()
        return {"ok": True, "message": "Nhà cung cấp đã có phiếu nhập nên không xóa được, đã chuyển sang ngừng hợp tác"}
    db.delete(s)
    db.commit()
    return {"ok": True, "message": "Đã xóa nhà cung cấp"}


# ---------------------------------------------------------------- Phiếu nhập
def po_out(po: ImportReceipt, user: User, with_items: bool = True) -> dict:
    hide = user.role == "staff"  # FR-PUR-08: nhân viên không thấy giá nhập
    data = {"id": po.id, "code": po.code, "supplier_id": po.supplier_id, "supplier": po.supplier,
            "status": po.status, "note": po.note, "total": None if hide else po.total,
            "created_at": po.created_at, "received_at": po.received_at, "cancelled_at": po.cancelled_at,
            "cancel_reason": po.cancel_reason, "user_id": po.user_id, "user_name": po.user.full_name,
            "item_count": len(po.items), "quantity": sum(i.quantity for i in po.items)}
    if with_items:
        data["items"] = [{
            "id": it.id, "product_id": it.product_id, "product_code": it.product.code,
            "product_name": it.product.name, "track_serial": it.product.track_serial, "quantity": it.quantity,
            "unit_cost": None if hide else it.unit_cost, "line_total": None if hide else it.line_total,
            "serials": it.serials or []} for it in po.items]
    return data


def _load(db: Session, po_id: int) -> ImportReceipt:
    po = db.scalar(select(ImportReceipt).options(selectinload(ImportReceipt.items).joinedload(ImportItem.product),
                                                 joinedload(ImportReceipt.user)).where(ImportReceipt.id == po_id))
    if po is None:
        raise HTTPException(404, "Không tìm thấy phiếu nhập")
    return po


def _run(db: Session, fn, *args):
    try:
        lock_for_write(db)  # mã chứng từ không trùng khi nhiều quầy ghi cùng lúc (FR-SAL-12)
        result = fn(*args)
        db.commit()
        return result
    except BusinessError as e:
        db.rollback()
        raise e.http()
    except IntegrityError:
        db.rollback()
        raise HTTPException(400, "Serial hoặc mã chứng từ bị trùng, vui lòng thử lại")


@router.get("/purchase-orders")
def list_purchase_orders(status: str | None = Query(None, pattern="^(draft|confirmed|cancelled)$"),
                         supplier_id: int | None = None, q: str | None = None,
                         date_from: str | None = None, date_to: str | None = None,
                         page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=200),
                         db: Session = Depends(get_db), user: User = Depends(ALL_STAFF)):
    stmt = select(ImportReceipt)
    if status:
        stmt = stmt.where(ImportReceipt.status == status)
    if supplier_id:
        stmt = stmt.where(ImportReceipt.supplier_id == supplier_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(ImportReceipt.code.ilike(like), ImportReceipt.supplier.ilike(like)))
    if date_from or date_to:
        start, end = parse_range(date_from, date_to)
        stmt = stmt.where(ImportReceipt.created_at >= start, ImportReceipt.created_at < end)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.options(joinedload(ImportReceipt.user), selectinload(ImportReceipt.items))
                      .order_by(ImportReceipt.created_at.desc(), ImportReceipt.id.desc())
                      .offset((page - 1) * size).limit(size)).unique().all()
    counts = dict(db.execute(select(ImportReceipt.status, func.count(ImportReceipt.id))
                             .group_by(ImportReceipt.status)).all())
    return {"total": total, "counts": counts, "items": [po_out(r, user, False) for r in rows]}


@router.get("/purchase-orders/restock-suggestions")
def restock_suggestions(db: Session = Depends(get_db), user: User = Depends(ALL_STAFF)):
    """Sản phẩm sắp hết kèm số lượng gợi ý nhập, nhà cung cấp và giá nhập lần gần nhất (nhập hàng nhanh)."""
    return restock.suggestions(db, user)


@router.post("/purchase-orders/quick-restock", status_code=201)
def quick_restock(data: QuickRestockIn, db: Session = Depends(get_db), user: User = Depends(ALL_STAFF)):
    return _run(db, restock.quick_restock, db, data, user)


@router.get("/purchase-orders/{po_id}")
def get_purchase_order(po_id: int, db: Session = Depends(get_db), user: User = Depends(ALL_STAFF)):
    return po_out(_load(db, po_id), user)


@router.post("/purchase-orders", status_code=201)
def create_purchase_order(data: PurchaseOrderIn, db: Session = Depends(get_db), user: User = Depends(ALL_STAFF)):
    """Nhân viên lập phiếu nháp không kèm giá nhập; chủ cửa hàng có thể lưu và xác nhận nhập kho ngay (confirm)."""
    po = _run(db, purchasing.create, db, data, user)
    return po_out(_load(db, po.id), user)


@router.put("/purchase-orders/{po_id}")
def update_purchase_order(po_id: int, data: PurchaseOrderIn, db: Session = Depends(get_db),
                          user: User = Depends(ALL_STAFF)):
    po = _load(db, po_id)
    _run(db, purchasing.update_draft, db, po, data, user)
    db.expire_all()
    return po_out(_load(db, po_id), user)


@router.delete("/purchase-orders/{po_id}")
def delete_purchase_order(po_id: int, db: Session = Depends(get_db), user: User = Depends(ALL_STAFF)):
    """FR-PUR-02: chỉ xóa được phiếu nháp (chưa đổi tồn kho)."""
    po = _load(db, po_id)
    if po.status != "draft":
        raise HTTPException(400, "Chỉ xóa được phiếu nháp. Phiếu đã xác nhận hãy dùng chức năng hủy")
    if user.role == "staff" and po.user_id != user.id:
        raise HTTPException(403, "Nhân viên chỉ xóa được phiếu nháp do mình lập")
    db.delete(po)
    db.commit()
    return {"ok": True}


@router.post("/purchase-orders/{po_id}/confirm")
def confirm_purchase_order(po_id: int, db: Session = Depends(get_db), user: User = Depends(MANAGERS)):
    po = _load(db, po_id)
    _run(db, purchasing.confirm, db, po, user)
    return po_out(_load(db, po_id), user)


@router.post("/purchase-orders/{po_id}/cancel")
def cancel_purchase_order(po_id: int, data: CancelIn, db: Session = Depends(get_db), user: User = Depends(MANAGERS)):
    po = _load(db, po_id)
    _run(db, purchasing.cancel, db, po, data.reason, user)
    return po_out(_load(db, po_id), user)
