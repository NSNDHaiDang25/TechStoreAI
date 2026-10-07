"""Đổi trả trong 24 giờ (SRS 3.2.3, 5.10; BR-30 đến BR-35) và bảo hành (3.2.4, 5.11; BR-36 đến BR-39)."""
from datetime import datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from app.models import (TICKET_OPEN, Customer, Invoice, InvoiceItem, ProductSerial, Promotion, Return, ReturnItem,
                        User, Warranty, WarrantyTicket, now)
from app.schemas import InvoiceIn, ReturnIn
from app.services import app_settings, audit, loyalty, sales
from app.services.codes import next_code
from app.services.inventory import BusinessError, _lock_products, change_stock


# ======================================================================= Đổi trả
def return_deadline(db: Session, inv: Invoice) -> datetime | None:
    if inv.paid_at is None:
        return None
    return inv.paid_at + timedelta(hours=app_settings.get(db, "return_window_hours"))


def _refund_for(it: InvoiceItem, qty: int) -> int:
    """BR-32: tiền hoàn = 'Còn lại' của dòng x tỷ lệ số lượng trả. Tính theo lũy kế để trả nhiều lần
    vẫn hoàn đúng tổng 'Còn lại' của dòng, không lệch do làm tròn."""
    before = it.net_total * it.returned_qty // it.quantity
    after = it.net_total * (it.returned_qty + qty) // it.quantity
    return after - before


def eligibility(db: Session, inv: Invoice) -> dict:
    deadline = return_deadline(db, inv)
    t = now()
    reason, reason_code = None, None
    if inv.status not in ("paid", "partially_returned"):
        reason_code = "INVOICE_NOT_RETURNABLE"
        reason = {"pending_payment": "Hóa đơn chưa thanh toán, chưa phát sinh doanh thu nên không đổi trả",
                  "draft": "Hóa đơn nháp", "cancelled": "Hóa đơn đã hủy",
                  "fully_returned": "Hóa đơn đã trả hết hàng"}.get(inv.status, "Hóa đơn không đổi trả được")
    elif deadline is None or t > deadline:
        reason_code = "RETURN_WINDOW_EXPIRED"
        reason = (f"Đã quá {app_settings.get(db, 'return_window_hours')} giờ kể từ lúc thanh toán. "
                  "Hàng lỗi vui lòng chuyển sang bảo hành")
    return {
        "invoice_id": inv.id, "code": inv.code, "status": inv.status, "paid_at": inv.paid_at, "deadline": deadline,
        "seconds_left": max(0, int((deadline - t).total_seconds())) if deadline else 0,
        "eligible": reason is None, "reason": reason, "reason_code": reason_code, "payment_method": inv.payment_method,
        "customer_name": inv.customer.name if inv.customer else "Khách lẻ",
        "lines": [{"invoice_item_id": it.id, "product_id": it.product_id, "product_code": it.product.code,
                   "product_name": it.product.name, "quantity": it.quantity, "returned_qty": it.returned_qty,
                   "returnable_qty": it.quantity - it.returned_qty, "net_total": it.net_total,
                   "unit_refund": it.net_total // it.quantity, "serial_id": it.serial_id,
                   "serial_no": it.serial.serial_no if it.serial else None} for it in inv.items],
    }


def create_return(db: Session, data: ReturnIn, user: User) -> Return:
    inv = db.get(Invoice, data.invoice_id)
    if inv is None:
        raise BusinessError("Không tìm thấy hóa đơn", "NOT_FOUND", 404)
    info = eligibility(db, inv)
    if not info["eligible"]:
        raise BusinessError(info["reason"], info["reason_code"])  # BR-30, FR-RET-02
    items = {it.id: it for it in inv.items}
    at = now()
    ret = Return(code=next_code(db, Return, "DT", at), invoice_id=inv.id, customer_id=inv.customer_id,
                 return_type="exchange" if data.exchange_items else "refund", reason=data.reason,
                 processed_by=user.id, created_at=at)
    db.add(ret)
    products = _lock_products(db, [items[i.invoice_item_id].product_id for i in data.items if i.invoice_item_id in items])
    seen: set[int] = set()
    for req in data.items:
        it = items.get(req.invoice_item_id)
        if it is None:
            raise BusinessError("Dòng hàng không thuộc hóa đơn này")
        if it.id in seen:
            raise BusinessError(f"Dòng '{it.product.name}' bị chọn hai lần")
        seen.add(it.id)
        if req.quantity > it.quantity - it.returned_qty:  # BR-31, FR-RET-03
            raise BusinessError(f"'{it.product.name}': chỉ trả được tối đa {it.quantity - it.returned_qty}",
                                    "RETURN_QTY_EXCEEDED")
        serial = None
        if it.serial_id:  # FR-RET-04: đối chiếu serial trả với serial trên hóa đơn
            given = (req.serial_no or "").strip().upper()
            serial = db.get(ProductSerial, it.serial_id)
            if not given or given != serial.serial_no:
                raise BusinessError(f"Serial trả lại không khớp serial đã bán của '{it.product.name}'", "SERIAL_MISMATCH")
        refund = _refund_for(it, req.quantity)
        restock = req.item_condition == "sellable"  # BR-33
        if restock:
            change_stock(db, products[it.product_id], req.quantity, "return", ret.code, user,
                         note=f"Khách trả hàng {inv.code}")
        if serial is not None:
            serial.status = "in_stock" if restock else "defective"
            serial.invoice_item_id = None if restock else serial.invoice_item_id
        it.returned_qty += req.quantity
        if it.returned_qty >= it.quantity:  # BR-37: vô hiệu hồ sơ bảo hành của dòng đã trả hết
            for w in db.scalars(select(Warranty).where(Warranty.invoice_item_id == it.id)):
                w.status = "void"
        ret.items.append(ReturnItem(invoice_item_id=it.id, serial_id=it.serial_id, quantity=req.quantity,
                                    refund_amount=refund, item_condition=req.item_condition, restock=restock))
    ret.refund_amount = sum(ri.refund_amount for ri in ret.items)

    # BR-35: trừ điểm đã tích theo tỷ lệ tiền hoàn, trừ tổng chi tiêu, tính lại hạng. Điểm đã dùng không hoàn.
    if inv.customer_id and inv.total:
        customer = db.get(Customer, inv.customer_id)
        ret.points_reversed = inv.points_earned * ret.refund_amount // inv.total
        if ret.points_reversed:
            loyalty.change_points(db, customer, -ret.points_reversed, "reverse_earn", invoice_id=inv.id,
                                  note=f"Đổi trả {ret.code}", user=user)
        customer.total_spent = max(0, customer.total_spent - ret.refund_amount)
        loyalty.recompute_tier(db, customer)

    fully = all(it.returned_qty >= it.quantity for it in inv.items)
    inv.status = "fully_returned" if fully else "partially_returned"
    if fully:  # BR-09: trả toàn bộ thì trả lại lượt dùng khuyến mãi
        promo_ids = ({inv.promotion_id} if inv.promotion_id else set()) | \
            {it.promotion_id for it in inv.items if it.promotion_id}
        for pid in promo_ids:
            promo = db.get(Promotion, pid)
            if promo is not None and promo.used_count > 0:
                promo.used_count -= 1
    db.flush()

    if data.exchange_items:  # BR-34: đổi sang sản phẩm khác bằng hóa đơn mới
        new_data = InvoiceIn(customer_id=inv.customer_id, items=data.exchange_items,
                             payment_method=data.exchange_payment_method, payment_ref=data.exchange_payment_ref,
                             payment_confirmed=True, note=f"Đổi hàng từ {inv.code} ({ret.code})")
        new_inv, _ = sales.checkout(db, new_data, user, at=at)
        ret.new_invoice_id = new_inv.id
    audit.log(db, user, "RETURN_CREATE", "returns", ret.id,
              new={"code": ret.code, "invoice": inv.code, "refund": ret.refund_amount, "type": ret.return_type})
    db.flush()
    return ret


def return_out(r: Return) -> dict:
    diff = (r.new_invoice.total - r.refund_amount) if r.new_invoice else None
    return {"id": r.id, "code": r.code, "invoice_id": r.invoice_id, "invoice_code": r.invoice.code,
            "customer_name": r.invoice.customer.name if r.invoice.customer else "Khách lẻ",
            "return_type": r.return_type, "reason": r.reason, "refund_amount": r.refund_amount,
            "refund_method": r.invoice.payment_method, "points_reversed": r.points_reversed,
            "new_invoice_id": r.new_invoice_id, "new_invoice_code": r.new_invoice.code if r.new_invoice else None,
            "new_invoice_total": r.new_invoice.total if r.new_invoice else None,
            "customer_pays": max(diff, 0) if diff is not None else None,
            "store_pays": max(-diff, 0) if diff is not None else r.refund_amount,
            "processed_by": r.user.full_name, "created_at": r.created_at,
            "items": [{"invoice_item_id": ri.invoice_item_id, "product_name": ri.invoice_item.product.name,
                       "serial_no": ri.invoice_item.serial.serial_no if ri.invoice_item.serial else None,
                       "quantity": ri.quantity, "refund_amount": ri.refund_amount,
                       "item_condition": ri.item_condition, "restock": ri.restock} for ri in r.items]}


# ======================================================================= Bảo hành
TRANSITIONS = {  # FR-WAR-07: sơ đồ trạng thái phiếu bảo hành (hình 3.8)
    "received": {"in_repair", "rejected"},
    "in_repair": {"waiting_parts", "done", "rejected"},
    "waiting_parts": {"in_repair", "done", "rejected"},
    "done": {"returned"},
    "rejected": {"returned"},
    "returned": set(),
}


def refresh_expired(db: Session) -> None:
    today = now().date()
    for w in db.scalars(select(Warranty).where(Warranty.status == "active", Warranty.end_date < today)):
        w.status = "expired"


def lookup(db: Session, q: str) -> list[Warranty]:
    """FR-WAR-02: tra theo serial / IMEI, số điện thoại khách hoặc mã hóa đơn."""
    refresh_expired(db)
    key = q.strip()
    stmt = select(Warranty).options(joinedload(Warranty.product), joinedload(Warranty.serial),
                                    joinedload(Warranty.customer), joinedload(Warranty.invoice_item))
    digits = key.replace(" ", "").replace(".", "")
    conds = [ProductSerial.serial_no.like(f"%{key.upper()}%"), Invoice.code == key.upper()]
    if digits.isdigit() and len(digits) >= 9:
        conds.append(Customer.phone == digits)
    stmt = (stmt.outerjoin(ProductSerial, Warranty.serial_id == ProductSerial.id)
            .outerjoin(Customer, Warranty.customer_id == Customer.id)
            .join(InvoiceItem, Warranty.invoice_item_id == InvoiceItem.id)
            .join(Invoice, InvoiceItem.invoice_id == Invoice.id)
            .where(or_(*conds)).order_by(Warranty.end_date.desc()).limit(100))
    return list(db.scalars(stmt).unique())


def open_ticket_for(db: Session, w: Warranty) -> WarrantyTicket | None:
    stmt = select(WarrantyTicket).join(Warranty).where(WarrantyTicket.status.in_(TICKET_OPEN))
    stmt = stmt.where(Warranty.serial_id == w.serial_id) if w.serial_id else stmt.where(Warranty.id == w.id)
    return db.scalar(stmt)


def warranty_out(db: Session, w: Warranty) -> dict:
    today = now().date()
    status = "expired" if w.status == "active" and w.end_date < today else w.status
    open_t = open_ticket_for(db, w)
    return {"id": w.id, "product_id": w.product_id, "product_code": w.product.code, "product_name": w.product.name,
            "serial_no": w.serial.serial_no if w.serial else None, "invoice_id": w.invoice_item.invoice_id,
            "invoice_code": w.invoice_item.invoice.code, "customer_id": w.customer_id,
            "customer_name": w.customer.name if w.customer else "Khách lẻ",
            "customer_phone": w.customer.phone if w.customer else None,
            "start_date": w.start_date, "end_date": w.end_date, "status": status,
            "days_left": (w.end_date - today).days if status == "active" else 0,
            "can_receive": status == "active" and open_t is None,
            "open_ticket": {"id": open_t.id, "code": open_t.code, "status": open_t.status} if open_t else None}


def create_ticket(db: Session, warranty_id: int, issue: str, user: User) -> WarrantyTicket:
    w = db.get(Warranty, warranty_id)
    if w is None:
        raise BusinessError("Không tìm thấy hồ sơ bảo hành", "NOT_FOUND", 404)
    refresh_expired(db)
    if w.status != "active":  # BR-38
        raise BusinessError("Hồ sơ bảo hành đã hết hạn" if w.status == "expired"
                            else "Hồ sơ bảo hành không còn hiệu lực (hàng đã trả hoặc hóa đơn đã hủy)",
                            "WARRANTY_EXPIRED" if w.status == "expired" else "WARRANTY_VOID")
    existing = open_ticket_for(db, w)
    if existing is not None:  # FR-WAR-04
        raise BusinessError(f"Máy đang có phiếu bảo hành {existing.code} chưa xử lý xong", "WARRANTY_TICKET_OPEN",
                                details={"ticket_id": existing.id, "ticket_code": existing.code})
    at = now()
    t = WarrantyTicket(code=next_code(db, WarrantyTicket, "BH", at), warranty_id=w.id, issue_description=issue,
                       status="received", received_by=user.id, received_at=at)
    db.add(t)
    if w.serial is not None and w.serial.status == "sold":
        w.serial.status = "in_warranty"
    db.flush()
    return t


def update_ticket(db: Session, t: WarrantyTicket, status: str | None, resolution: str | None, user: User) -> WarrantyTicket:
    if status and status != t.status:
        if status not in TRANSITIONS[t.status]:
            raise BusinessError(f"Không chuyển được từ '{t.status}' sang '{status}'")  # FR-WAR-07
        if status in ("done", "rejected") and not (resolution or t.resolution):
            raise BusinessError("Nhập kết quả xử lý trước khi hoàn tất hoặc từ chối bảo hành")
        t.status = status
        if status in ("done", "rejected"):
            t.completed_at = now()
        if status == "returned":
            t.returned_at = now()
            serial = t.warranty.serial
            if serial is not None and serial.status == "in_warranty":
                serial.status = "sold"
    if resolution is not None:
        t.resolution = resolution.strip() or None
    db.flush()
    return t


def ticket_out(t: WarrantyTicket) -> dict:
    w = t.warranty
    return {"id": t.id, "code": t.code, "warranty_id": w.id, "status": t.status,
            "issue_description": t.issue_description, "resolution": t.resolution,
            "product_name": w.product.name, "serial_no": w.serial.serial_no if w.serial else None,
            "invoice_code": w.invoice_item.invoice.code, "customer_name": w.customer.name if w.customer else "Khách lẻ",
            "customer_phone": w.customer.phone if w.customer else None,
            "customer_email": w.customer.email if w.customer else None,
            "warranty_end": w.end_date, "received_by": t.user.full_name, "received_at": t.received_at,
            "completed_at": t.completed_at, "returned_at": t.returned_at,
            "next_statuses": sorted(TRANSITIONS[t.status])}
