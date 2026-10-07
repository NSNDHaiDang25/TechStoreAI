"""Bán hàng và hóa đơn (SRS 3.2.1, 3.2.5, 5.8, 5.9).

Vòng đời hóa đơn (bảng 3.2): draft -> pending_payment -> paid -> partially_returned / fully_returned,
hoặc -> cancelled. Tồn kho trừ khi chốt (pending_payment hoặc paid); điểm, tổng chi tiêu, hồ sơ bảo hành
chỉ phát sinh khi hóa đơn paid. Mọi bước nằm trong một giao dịch CSDL: các hàm ở đây không commit,
router commit sau khi toàn bộ nghiệp vụ thành công (FR-SAL-08).
"""
import calendar
from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (PAID_STATES, Customer, Invoice, InvoiceItem, Payment, Product, ProductSerial, Promotion,
                        Return, User, Warranty, now)
from app.schemas import InvoiceIn
from app.services import app_settings, audit, loyalty, pricing
from app.services.codes import next_code
from app.services.inventory import BusinessError, _lock_products, change_stock
from app.services.pricing import Line, PricingError

LEGACY_METHODS = {"transfer": "bank_transfer", "qr": "bank_transfer"}


def add_months(d: date, months: int) -> date:
    """Cộng tháng, ngày 31 rơi vào tháng ngắn thì lấy ngày cuối tháng (31/01 + 1 tháng = 28/02)."""
    m = d.month - 1 + months
    year, month = d.year + m // 12, m % 12 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


# ---------------------------------------------------------------- Giỏ hàng
def _customer(db: Session, customer_id: int | None) -> Customer | None:
    if customer_id is None:
        return None
    c = db.get(Customer, customer_id)
    if c is None:
        raise BusinessError("Khách hàng không tồn tại")
    if not c.is_active:
        raise BusinessError("Khách hàng đã bị vô hiệu hóa")
    return c


def build_lines(db: Session, data: InvoiceIn, user: User, *, for_sale: bool,
                own_serials: set[int] | None = None) -> list[Line]:
    """Dựng các dòng hàng: kiểm tra trạng thái sản phẩm, tồn kho (FR-SAL-03), serial (FR-SAL-04, BR-18).
    own_serials: serial đang thuộc chính hóa đơn được sửa (vẫn chọn lại được)."""
    products = _lock_products(db, [i.product_id for i in data.items])
    lines: list[Line] = []
    merged: dict[tuple[int, int], Line] = {}
    used_serials: set[int] = set()
    for item in data.items:
        p = products[item.product_id]
        if p.status != "active":
            raise BusinessError(f"Sản phẩm '{p.name}' đang ngừng kinh doanh")  # FR-PRD-03
        price = item.unit_price if (item.unit_price is not None and user.role != "staff") else p.sale_price
        if p.track_serial:
            serial = _pick_serial(db, p, item, for_sale, own_serials or set())
            if serial is not None:
                if serial.id in used_serials:
                    raise BusinessError(f"Serial {serial.serial_no} bị chọn hai lần")
                used_serials.add(serial.id)
            if item.quantity != 1 and (serial is not None or for_sale):
                raise BusinessError(f"'{p.name}' quản lý theo serial: mỗi dòng một máy, số lượng bằng 1")
            lines.append(Line(product=p, quantity=1 if serial is not None else item.quantity, unit_price=price,
                              serial=serial))
            continue
        key = (p.id, price)  # gộp các dòng trùng sản phẩm để kiểm tra tồn kho chính xác
        if key in merged:
            merged[key].quantity += item.quantity
        else:
            merged[key] = Line(product=p, quantity=item.quantity, unit_price=price)
            lines.append(merged[key])
    if for_sale:
        need: dict[int, int] = defaultdict(int)
        for ln in lines:
            need[ln.product.id] += ln.quantity
        for pid, qty in need.items():
            p = products[pid]
            if qty > p.stock:
                raise BusinessError(f"Sản phẩm '{p.name}' không đủ tồn kho (còn {p.stock}, cần {qty})", "OUT_OF_STOCK",
                                    details={"product_id": p.id, "available": p.stock, "requested": qty})
    return lines


def _pick_serial(db: Session, product: Product, item, for_sale: bool, own: set[int]) -> ProductSerial | None:
    serial = None
    if item.serial_id:
        serial = db.get(ProductSerial, item.serial_id)
    elif item.serial_no:
        serial = db.scalar(select(ProductSerial).where(ProductSerial.serial_no == item.serial_no.strip().upper()))
    elif for_sale:
        raise BusinessError(f"'{product.name}' quản lý theo serial: hãy chọn serial / IMEI của máy bán",
                            "SERIAL_REQUIRED", 422, {"product_id": product.id})
    else:
        return None
    if serial is None or serial.product_id != product.id:
        raise BusinessError(f"Serial không thuộc sản phẩm '{product.name}'")
    if serial.status != "in_stock" and serial.id not in own:
        raise BusinessError(f"Serial {serial.serial_no} không còn trong kho (trạng thái {serial.status})",
                            "SERIAL_NOT_AVAILABLE")
    return serial


def preview(db: Session, data: InvoiceIn, user: User, own_promotion: int | None = None) -> pricing.Cart:
    """Tính thử giỏ hàng (FR-SAL-05, FR-PRM-05), không ghi gì. own_promotion: khuyến mãi hóa đơn đang sửa đã giữ lượt."""
    customer = _customer(db, data.customer_id)
    lines = build_lines(db, data, user, for_sale=False)
    try:
        return pricing.compute(db, lines, customer, promo_code=data.promo_code, points_used=data.points_used,
                               manual_discount=data.discount, manual_percent=data.discount_percent,
                               exclude_promotion_usage=own_promotion)
    except PricingError as e:
        raise BusinessError(str(e), "PRICING_INVALID")


# ---------------------------------------------------------------- Ghi hóa đơn
def _promotion_ids(cart: pricing.Cart) -> set[int]:
    ids = {ln.line_promo_id for ln in cart.lines if ln.line_promo_id}
    if cart.invoice_promo:
        ids.add(cart.invoice_promo.id)
    return ids


def _fill(inv: Invoice, cart: pricing.Cart, data: InvoiceIn) -> None:
    inv.customer_id = cart.customer.id if cart.customer else None
    inv.note = data.note
    inv.subtotal, inv.total, inv.vat_amount = cart.subtotal, cart.total, cart.vat_amount
    inv.promo_discount, inv.points_discount, inv.discount = cart.promo_discount, cart.points_discount, cart.discount
    inv.promotion_id = cart.invoice_promo.id if cart.invoice_promo else None
    inv.points_used, inv.points_earned = cart.points_used, cart.points_earned
    for ln in cart.lines:
        inv.items.append(InvoiceItem(
            product_id=ln.product.id, serial_id=ln.serial.id if ln.serial else None, quantity=ln.quantity,
            unit_price=ln.unit_price, unit_cost=ln.product.cost_price, line_total=ln.line_total,
            discount_amount=ln.discount_amount, vat_rate=ln.product.vat_rate or 0, vat_amount=ln.vat_amount,
            warranty_months=ln.product.warranty_months, promotion_id=ln.line_promo_id))


def _below_cost_guard(db: Session, cart: pricing.Cart, user: User, inv: Invoice) -> None:
    """BR-03 / FR-SAL-14: nhân viên không bán được dưới giá vốn; chủ cửa hàng bán được, hệ thống ghi audit log."""
    if not cart.below_cost:
        return
    if user.role == "staff":
        raise BusinessError("Giá sau giảm thấp hơn giá vốn, cần chủ cửa hàng xác nhận: " + "; ".join(cart.below_cost),
                            "BELOW_COST")
    audit.log(db, user, "INVOICE_BELOW_COST", "invoices", inv.id, new=cart.below_cost)


def save_draft(db: Session, data: InvoiceIn, user: User, existing: Invoice | None = None) -> tuple[Invoice, pricing.Cart]:
    """FR-SAL-07: lưu giỏ hàng nháp, chưa trừ tồn, để khôi phục khi mất kết nối hoặc đóng nhầm trình duyệt."""
    if existing is not None and existing.status != "draft":
        raise BusinessError("Chỉ lưu nháp cho hóa đơn đang ở trạng thái nháp")
    cart = preview(db, data, user)
    at = now()
    inv = existing or Invoice(code=next_code(db, Invoice, "HD", at, 4), user_id=user.id, created_at=at)
    if existing is None:
        db.add(inv)
    inv.items.clear()
    db.flush()
    inv.status = "draft"
    inv.payment_method = LEGACY_METHODS.get(data.payment_method, data.payment_method)
    _fill(inv, cart, data)
    db.flush()
    return inv, cart


def checkout(db: Session, data: InvoiceIn, user: User, existing: Invoice | None = None,
             at: datetime | None = None) -> tuple[Invoice, pricing.Cart]:
    """Chốt hóa đơn: trừ tồn, ghi thẻ kho, đánh dấu serial đã bán, tính tiền; thanh toán xong thì cộng điểm,
    tạo bảo hành. existing: hóa đơn nháp hoặc chờ thanh toán đang được chốt / sửa (giữ nguyên mã)."""
    at = at or now()
    own_serials: set[int] = set()
    if existing is not None:
        if existing.status not in ("draft", "pending_payment"):
            raise BusinessError("Hóa đơn đã thanh toán không sửa được (BR-24)", "INVOICE_LOCKED")
        if existing.status == "pending_payment":
            # Trả tồn kho, serial, lượt khuyến mãi của bản cũ rồi chốt lại như hóa đơn mới (giữ mã)
            _release_stock_and_promos(db, existing, user, "edit")
        own_serials = {it.serial_id for it in existing.items if it.serial_id}
        existing.items.clear()
        db.flush()
    customer = _customer(db, data.customer_id)
    lines = build_lines(db, data, user, for_sale=True, own_serials=own_serials)
    try:
        cart = pricing.compute(db, lines, customer, promo_code=data.promo_code, points_used=data.points_used,
                               manual_discount=data.discount, manual_percent=data.discount_percent, at=at)
    except PricingError as e:
        raise BusinessError(str(e), "PRICING_INVALID")
    method = LEGACY_METHODS.get(data.payment_method, data.payment_method)
    if existing is not None:
        inv = existing
    else:
        inv = Invoice(code=next_code(db, Invoice, "HD", at, 4), user_id=user.id, created_at=at)
        db.add(inv)
    inv.payment_method = method
    _fill(inv, cart, data)
    db.flush()
    _below_cost_guard(db, cart, user, inv)

    for it, ln in zip(inv.items, cart.lines):
        change_stock(db, ln.product, -ln.quantity, "sale" if existing is None else "edit", inv.code, user, at=at)
        if ln.serial is not None:
            ln.serial.status = "sold"
            ln.serial.invoice_item_id = it.id
    for pid in _promotion_ids(cart):
        promo = db.get(Promotion, pid)
        if promo.usage_limit is not None and promo.used_count >= promo.usage_limit:
            raise BusinessError(f"Khuyến mãi '{promo.name}' vừa hết lượt sử dụng", "PROMOTION_USED_UP")
        promo.used_count += 1
    inv.payment_ref = (data.payment_ref or "").strip() or None
    inv.cash_received = None
    confirmed = True
    if method == "cash":
        if data.cash_received is not None:
            if data.cash_received < inv.total:
                raise BusinessError("Tiền khách đưa ít hơn tổng tiền cần thanh toán", "CASH_NOT_ENOUGH", 422)  # BR-27
            inv.cash_received = data.cash_received
    elif method == "card":
        if not inv.payment_ref:
            raise BusinessError("Thanh toán thẻ: nhập mã giao dịch in trên biên lai máy POS", "POS_REFERENCE_REQUIRED", 422)  # BR-29
    else:  # bank_transfer: chờ nhân viên xác nhận đã nhận tiền (BR-28), trừ khi đã xác nhận ngay tại quầy
        confirmed = data.payment_confirmed or data.payment_method in LEGACY_METHODS
        inv.payment_ref = inv.payment_ref or inv.code
    from app.services.qr import vietqr_payload
    qr = None
    if method == "bank_transfer":
        bank = app_settings.get_many(db, ["bank_bin", "bank_account"])
        qr = vietqr_payload(bank["bank_bin"], bank["bank_account"], inv.total, inv.code)
    for old in inv.payments:
        if old.status == "pending":
            old.status = "failed"
    inv.payments.append(Payment(method=method, amount=inv.total, status="confirmed" if confirmed else "pending",
                                reference_code=inv.payment_ref, qr_payload=qr,
                                confirmed_by=user.id if confirmed else None, confirmed_at=at if confirmed else None))
    if confirmed:
        finalize_paid(db, inv, user, at)
    else:
        inv.status = "pending_payment"
    db.flush()
    return inv, cart


def finalize_paid(db: Session, inv: Invoice, user: User, at: datetime | None = None) -> None:
    """Hóa đơn chuyển paid: trừ điểm đã dùng, cộng điểm (BR-11), cộng tổng chi tiêu, tính lại hạng,
    tạo hồ sơ bảo hành cho từng dòng (FR-WAR-01)."""
    at = at or now()
    inv.status = "paid"
    inv.paid_at = at
    customer = db.get(Customer, inv.customer_id) if inv.customer_id else None
    if customer is not None:
        if inv.points_used:
            if inv.points_used > customer.loyalty_points:
                raise BusinessError(f"Khách chỉ còn {customer.loyalty_points} điểm, không đủ {inv.points_used} điểm",
                                    "INSUFFICIENT_POINTS")
            loyalty.change_points(db, customer, -inv.points_used, "redeem", invoice_id=inv.id,
                                  note=f"Dùng điểm cho {inv.code}", user=user)
        inv.points_earned = loyalty.points_for(db, customer, inv.total)
        loyalty.change_points(db, customer, inv.points_earned, "earn", invoice_id=inv.id,
                              note=f"Tích điểm {inv.code}", user=user)
        customer.total_spent += inv.total
        loyalty.recompute_tier(db, customer)
    else:
        inv.points_earned = 0
    start = at.date()
    for it in inv.items:
        if it.warranty_months > 0:
            db.add(Warranty(invoice_item_id=it.id, product_id=it.product_id, serial_id=it.serial_id,
                            customer_id=inv.customer_id, start_date=start,
                            end_date=add_months(start, it.warranty_months), status="active"))


def confirm_payment(db: Session, inv: Invoice, user: User, method: str | None = None,
                    payment_ref: str | None = None, cash_received: int | None = None) -> Invoice:
    """FR-PAY-05, 06: nhân viên xác nhận đã nhận tiền; có thể đổi phương thức khi hóa đơn còn chờ thanh toán."""
    if inv.status != "pending_payment":
        raise BusinessError("Hóa đơn không ở trạng thái chờ thanh toán")
    method = LEGACY_METHODS.get(method, method) if method else inv.payment_method
    ref = (payment_ref or "").strip() or None
    if method == "card" and not ref:
        raise BusinessError("Thanh toán thẻ: nhập mã giao dịch in trên biên lai máy POS", "POS_REFERENCE_REQUIRED", 422)
    if method == "cash" and cash_received is not None and cash_received < inv.total:
        raise BusinessError("Tiền khách đưa ít hơn tổng tiền cần thanh toán", "CASH_NOT_ENOUGH", 422)
    at = now()
    pending = next((p for p in inv.payments if p.status == "pending"), None)
    if pending is None or pending.method != method:
        if pending is not None:
            pending.status = "failed"
        pending = Payment(method=method, amount=inv.total, status="pending")
        inv.payments.append(pending)
    pending.status, pending.confirmed_by, pending.confirmed_at = "confirmed", user.id, at
    pending.reference_code = ref or pending.reference_code or inv.code
    inv.payment_method = method
    inv.payment_ref = pending.reference_code
    inv.cash_received = cash_received if method == "cash" else None
    finalize_paid(db, inv, user, at)
    db.flush()
    return inv


# ---------------------------------------------------------------- Hủy hóa đơn
def _release_stock_and_promos(db: Session, inv: Invoice, user: User | None, move_type: str) -> set[int]:
    """Hoàn tồn kho phần chưa trả, trả serial về kho, trả lượt dùng khuyến mãi (BR-09). Trả về id khuyến mãi đã trả."""
    products = _lock_products(db, [i.product_id for i in inv.items]) if inv.items else {}
    for it in inv.items:
        qty = it.quantity - it.returned_qty
        if qty > 0:
            change_stock(db, products[it.product_id], qty, move_type, inv.code, user)
        if it.serial_id:
            serial = db.get(ProductSerial, it.serial_id)
            if serial is not None and serial.status == "sold":
                serial.status, serial.invoice_item_id = "in_stock", None
    released = set()
    promo_ids = {inv.promotion_id} if inv.promotion_id else set()
    promo_ids |= {it.promotion_id for it in inv.items if it.promotion_id}
    for pid in promo_ids:
        promo = db.get(Promotion, pid)
        if promo is not None and promo.used_count > 0:
            promo.used_count -= 1
            released.add(pid)
    return released


def cancel(db: Session, inv: Invoice, reason: str, user: User, *, system: bool = False) -> Invoice:
    """FR-SAL-09, BR-25: hủy hóa đơn lập sai. Hóa đơn đã thanh toán chỉ hủy trong ngày lập, khi chưa có
    phiếu đổi trả, và do chủ cửa hàng thực hiện hoặc duyệt. Hoàn tồn kho, điểm, voucher, bảo hành."""
    if inv.status == "cancelled":
        raise BusinessError("Hóa đơn đã bị hủy trước đó")
    if inv.status in ("partially_returned", "fully_returned") or \
            db.scalar(select(Return.id).where(Return.invoice_id == inv.id)):
        raise BusinessError("Hóa đơn đã có phiếu đổi trả, không thể hủy", "CANCEL_NOT_ALLOWED")
    was_paid = inv.status == "paid"
    if was_paid:
        if not system and user.role == "staff":
            raise BusinessError("Hóa đơn đã thanh toán cần chủ cửa hàng duyệt hủy", "APPROVAL_REQUIRED")
        if inv.created_at.date() != now().date():
            raise BusinessError("Chỉ hủy được hóa đơn trong ngày lập. Khách đổi ý hoặc hàng lỗi hãy dùng đổi trả",
                                  "CANCEL_WINDOW_EXPIRED")
    if inv.status != "draft":
        _release_stock_and_promos(db, inv, user, "cancel")
    if was_paid and inv.customer_id:
        customer = db.get(Customer, inv.customer_id)
        if inv.points_earned:
            loyalty.change_points(db, customer, -inv.points_earned, "reverse_earn", invoice_id=inv.id,
                                  note=f"Hủy {inv.code}", user=user)
        if inv.points_used:
            loyalty.change_points(db, customer, inv.points_used, "reverse_redeem", invoice_id=inv.id,
                                  note=f"Hoàn điểm đã dùng, hủy {inv.code}", user=user)
        customer.total_spent = max(0, customer.total_spent - inv.total)
        loyalty.recompute_tier(db, customer)
    for w in db.scalars(select(Warranty).join(InvoiceItem).where(InvoiceItem.invoice_id == inv.id)):
        w.status = "void"  # BR-37
    for p in inv.payments:
        if p.status == "pending":
            p.status = "failed"
    old_status = inv.status
    inv.status = "cancelled"
    inv.cancelled_at = now()
    inv.cancelled_by = None if system else user.id
    inv.cancel_reason = reason
    inv.cancel_requested_at = None
    if not system:
        audit.log(db, user, "INVOICE_CANCEL", "invoices", inv.id, old={"status": old_status, "total": inv.total},
                  new={"status": "cancelled", "reason": reason})
    db.flush()
    return inv


def request_cancel(db: Session, inv: Invoice, reason: str, user: User) -> Invoice:
    """FR-SAL-10: nhân viên gửi yêu cầu hủy hóa đơn đã thanh toán, chờ chủ cửa hàng duyệt."""
    if inv.status != "paid":
        raise BusinessError("Chỉ gửi yêu cầu hủy cho hóa đơn đã thanh toán")
    if inv.created_at.date() != now().date():
        raise BusinessError("Chỉ hủy được hóa đơn trong ngày lập. Khách đổi ý hoặc hàng lỗi hãy dùng đổi trả",
                                  "CANCEL_WINDOW_EXPIRED")
    if inv.cancel_requested_at:
        raise BusinessError("Hóa đơn đã có yêu cầu hủy đang chờ duyệt")
    inv.cancel_requested_by, inv.cancel_requested_at, inv.cancel_reason = user.id, now(), reason
    audit.log(db, user, "INVOICE_CANCEL_REQUEST", "invoices", inv.id, new={"reason": reason})
    db.flush()
    return inv


def decide_cancel(db: Session, inv: Invoice, approve: bool, user: User, note: str | None = None) -> Invoice:
    if not inv.cancel_requested_at or inv.status != "paid":
        raise BusinessError("Hóa đơn không có yêu cầu hủy đang chờ duyệt")
    if approve:
        return cancel(db, inv, inv.cancel_reason or "Duyệt yêu cầu hủy", user)
    audit.log(db, user, "INVOICE_CANCEL_REJECT", "invoices", inv.id, old={"reason": inv.cancel_reason},
              new={"note": note})
    inv.cancel_requested_at = inv.cancel_requested_by = None
    inv.cancel_reason = None
    db.flush()
    return inv


def expire_pending(db: Session) -> int:
    """BR-26 / FR-SAL-15: hóa đơn chờ chuyển khoản quá pending_payment_minutes tự hủy và hoàn tồn kho."""
    minutes = app_settings.get(db, "pending_payment_minutes")
    limit = now() - timedelta(minutes=minutes)
    stale = db.scalars(select(Invoice).where(Invoice.status == "pending_payment", Invoice.created_at < limit)).all()
    for inv in stale:
        cancel(db, inv, f"Quá {minutes} phút chờ chuyển khoản", inv.user, system=True)
    return len(stale)


def pending_deadline(db: Session, inv: Invoice) -> datetime | None:
    if inv.status != "pending_payment":
        return None
    return inv.created_at + timedelta(minutes=app_settings.get(db, "pending_payment_minutes"))


def is_revenue(inv: Invoice) -> bool:
    return inv.status in PAID_STATES
