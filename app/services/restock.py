"""Nhập hàng nhanh khi sắp hết (FR-STK-02 mở rộng): gợi ý số lượng cần nhập và lập phiếu nhập theo từng nhà cung cấp.

Số lượng gợi ý = đủ bán khoảng 30 ngày theo tốc độ bán 30 ngày qua, ít nhất gấp đôi mức tồn tối thiểu,
trừ tồn hiện có và số đang nằm trong phiếu nhập nháp (tránh đặt trùng).
Nhà cung cấp và giá nhập gợi ý lấy theo lần nhập kho gần nhất của sản phẩm.
"""
import math
from collections import defaultdict
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import PAID_STATES, ImportItem, ImportReceipt, Invoice, InvoiceItem, Product, Supplier, User, now
from app.schemas import PurchaseItemIn, PurchaseOrderIn, QuickRestockIn
from app.services import purchasing
from app.services.inventory import BusinessError

SALES_DAYS = 30
NOTE = "Nhập hàng nhanh (hàng sắp hết)"


def suggestions(db: Session, user: User) -> dict:
    products = db.scalars(select(Product).where(Product.status == "active", Product.stock < Product.min_stock)
                          .order_by(Product.stock, Product.name)).all()
    ids = [p.id for p in products]
    if not ids:
        return {"items": [], "suppliers": _suppliers(db), "days": SALES_DAYS}
    since = now() - timedelta(days=SALES_DAYS)
    sold = dict(db.execute(
        select(InvoiceItem.product_id, func.sum(InvoiceItem.quantity - InvoiceItem.returned_qty))
        .join(Invoice).where(InvoiceItem.product_id.in_(ids), Invoice.status.in_(PAID_STATES), Invoice.paid_at >= since)
        .group_by(InvoiceItem.product_id)).all())
    pending = dict(db.execute(
        select(ImportItem.product_id, func.sum(ImportItem.quantity)).join(ImportReceipt)
        .where(ImportItem.product_id.in_(ids), ImportReceipt.status == "draft").group_by(ImportItem.product_id)).all())
    # Lần nhập kho gần nhất của từng sản phẩm: nhà cung cấp và giá nhập
    last = {}
    rows = db.execute(
        select(ImportItem.product_id, ImportReceipt.supplier_id, ImportItem.unit_cost).join(ImportReceipt)
        .where(ImportItem.product_id.in_(ids), ImportReceipt.status == "confirmed")
        .order_by(ImportReceipt.received_at.desc(), ImportReceipt.id.desc())).all()
    for pid, sup_id, cost in rows:
        last.setdefault(pid, (sup_id, cost))
    items = []
    for p in products:
        sold_qty = int(sold.get(p.id) or 0)
        waiting = int(pending.get(p.id) or 0)
        target = max(p.min_stock * 2, sold_qty)
        sup_id, cost = last.get(p.id, (None, None))
        item = {"product_id": p.id, "code": p.code, "name": p.name, "image_url": p.image_url, "stock": p.stock,
                "min_stock": p.min_stock, "track_serial": p.track_serial, "sold_30d": sold_qty, "pending_qty": waiting,
                "suggested_qty": max(0, math.ceil(target - p.stock - waiting)), "supplier_id": sup_id,
                "unit_cost": cost or p.cost_price}
        if user.role == "staff":
            item.pop("unit_cost")  # nhân viên không thấy giá nhập (FR-PRD-08)
        items.append(item)
    return {"items": items, "suppliers": _suppliers(db), "days": SALES_DAYS}


def _suppliers(db: Session) -> list[dict]:
    rows = db.scalars(select(Supplier).where(Supplier.status == "active").order_by(Supplier.name)).all()
    return [{"id": s.id, "code": s.code, "name": s.name} for s in rows]


def quick_restock(db: Session, data: QuickRestockIn, user: User) -> dict:
    """Lập một phiếu nhập cho mỗi nhà cung cấp. confirm (chủ cửa hàng): nhập kho ngay các phiếu không có sản phẩm
    quản lý serial (serial phải nhập tay ở phiếu), phiếu còn lại giữ nháp."""
    ids = [it.product_id for it in data.items]
    if len(set(ids)) != len(ids):
        raise BusinessError("Mỗi sản phẩm chỉ chọn một lần")
    if data.confirm and user.role == "staff":
        raise BusinessError("Nhân viên chỉ lập phiếu nháp, chủ cửa hàng xác nhận nhập kho")
    groups = defaultdict(list)
    for it in data.items:
        groups[it.supplier_id].append(it)
    serial = set(db.scalars(select(Product.id).where(Product.id.in_(ids), Product.track_serial.is_(True))).all())
    created = []
    for sup_id, items in groups.items():
        po = purchasing.create(db, PurchaseOrderIn(
            supplier_id=sup_id, note=data.note or NOTE,
            items=[PurchaseItemIn(product_id=i.product_id, quantity=i.quantity, unit_cost=i.unit_cost) for i in items]), user)
        received = data.confirm and not any(i.product_id in serial for i in items) and all(i.unit_cost for i in items)
        if received:
            purchasing.confirm(db, po, user)
        created.append({"id": po.id, "code": po.code, "supplier": po.supplier, "status": po.status,
                        "item_count": len(items), "has_serial": any(i.product_id in serial for i in items)})
    return {"orders": created}
