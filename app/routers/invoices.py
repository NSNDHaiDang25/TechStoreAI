"""Hóa đơn bán hàng (UC-19 đến UC-30) và phiếu nhập kiểu cũ (/api/imports)."""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.database import get_db, lock_for_write
from app.models import (PAID_STATES, Customer, ImportReceipt, Invoice, InvoiceItem, Return, User, Warranty)
from app.schemas import (CancelDecisionIn, ConfirmPaymentIn, EmailInvoiceIn, ImportIn, InvoiceCancelIn, InvoiceIn)
from app.security import ALL_STAFF, MANAGERS
from app.services import app_settings, audit, inventory, receipts, sales
from app.services.inventory import BusinessError
from app.services.mailer import MailError, mail_configured, send_logged
from app.services.qr import qr_svg, vietqr_payload
from app.services.reports import parse_range

router = APIRouter(prefix="/api", tags=["invoices"])
STATUS_PATTERN = "^(draft|pending_payment|paid|partially_returned|fully_returned|cancelled|revenue)$"


def mask_phone(phone: str | None) -> str | None:
    """BR-40: che số điện thoại dạng 0912 *** 678 ở danh sách."""
    if not phone or len(phone) < 7:
        return phone
    return f"{phone[:4]} *** {phone[-3:]}"


def invoice_out(inv: Invoice, with_items: bool = True, db: Session | None = None, user: User | None = None) -> dict:
    hide_cost = user is not None and user.role == "staff"
    data = {
        "id": inv.id, "code": inv.code, "customer_id": inv.customer_id,
        "customer_name": inv.customer.name if inv.customer else "Khách lẻ",
        "customer_phone": inv.customer.phone if (inv.customer and with_items) else
        (mask_phone(inv.customer.phone) if inv.customer else None),
        "user_id": inv.user_id, "user_name": inv.user.full_name, "created_at": inv.created_at,
        "paid_at": inv.paid_at, "subtotal": inv.subtotal, "promo_discount": inv.promo_discount,
        "points_discount": inv.points_discount, "discount": inv.discount, "total": inv.total,
        "vat_amount": inv.vat_amount, "revenue_net": inv.total - inv.vat_amount,
        "promotion_id": inv.promotion_id, "promotion_code": inv.promotion.code if inv.promotion else None,
        "promotion_name": inv.promotion.name if inv.promotion else None,
        "points_used": inv.points_used, "points_earned": inv.points_earned,
        "payment_method": inv.payment_method, "cash_received": inv.cash_received,
        "change": inv.cash_received - inv.total if inv.cash_received is not None else None,
        "payment_ref": inv.payment_ref, "status": inv.status, "note": inv.note,
        "cancelled_at": inv.cancelled_at, "cancel_reason": inv.cancel_reason,
        "cancel_requested_at": inv.cancel_requested_at, "print_count": inv.print_count,
    }
    if db is not None:
        deadline = sales.pending_deadline(db, inv)
        data["pending_deadline"] = deadline
    if with_items:
        data["items"] = [{
            "id": it.id, "product_id": it.product_id, "product_code": it.product.code,
            "product_name": it.product.name, "image_url": it.product.image_url, "quantity": it.quantity,
            "unit_price": it.unit_price, "line_total": it.line_total, "discount_amount": it.discount_amount,
            "net_total": it.net_total, "vat_rate": it.vat_rate, "vat_amount": it.vat_amount,
            "returned_qty": it.returned_qty, "warranty_months": it.warranty_months,
            "serial_id": it.serial_id, "serial_no": it.serial.serial_no if it.serial else None,
            "unit_cost": None if hide_cost else it.unit_cost,
        } for it in inv.items]
        data["payments"] = [{"id": p.id, "method": p.method, "amount": p.amount, "status": p.status,
                             "reference_code": p.reference_code, "confirmed_at": p.confirmed_at}
                            for p in inv.payments]
    return data


def invoice_query(user: User, q: str | None, status: str | None, date_from: str | None,
                  date_to: str | None, payment_method: str | None, customer_id: int | None,
                  cashier_id: int | None = None):
    stmt = select(Invoice)
    if user.role == "staff":
        stmt = stmt.where(Invoice.user_id == user.id)  # nhân viên chỉ xem hóa đơn mình lập
    elif cashier_id:
        stmt = stmt.where(Invoice.user_id == cashier_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.outerjoin(Customer).where(
            or_(Invoice.code.ilike(like), Customer.name.ilike(like), Customer.phone.ilike(like)))
    if status == "revenue":
        stmt = stmt.where(Invoice.status.in_(PAID_STATES))
    elif status:
        stmt = stmt.where(Invoice.status == status)
    if payment_method:
        stmt = stmt.where(Invoice.payment_method == sales.LEGACY_METHODS.get(payment_method, payment_method))
    if customer_id:
        stmt = stmt.where(Invoice.customer_id == customer_id)
    if date_from or date_to:
        start, end = parse_range(date_from, date_to)
        stmt = stmt.where(Invoice.created_at >= start, Invoice.created_at < end)
    return stmt


def _expire(db: Session) -> None:
    if sales.expire_pending(db):
        db.commit()


@router.get("/invoices")
def list_invoices(q: str | None = None, status: str | None = Query(None, pattern=STATUS_PATTERN),
                  date_from: str | None = None, date_to: str | None = None,
                  payment_method: str | None = None, customer_id: int | None = None,
                  cashier_id: int | None = None, cancel_requested: bool = False,
                  page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=200),
                  db: Session = Depends(get_db), user: User = Depends(ALL_STAFF)):
    """FR-SAL-13: tìm và lọc theo mã, khách, ngày, trạng thái, phương thức thanh toán, nhân viên."""
    _expire(db)
    stmt = invoice_query(user, q, status, date_from, date_to, payment_method, customer_id, cashier_id)
    if cancel_requested:
        stmt = stmt.where(Invoice.cancel_requested_at.is_not(None), Invoice.status == "paid")
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    sum_total = db.scalar(select(func.coalesce(func.sum(Invoice.total), 0)).where(
        Invoice.id.in_(stmt.with_only_columns(Invoice.id).where(Invoice.status.in_(PAID_STATES)))))
    stmt = stmt.options(joinedload(Invoice.customer), joinedload(Invoice.user), joinedload(Invoice.promotion))
    rows = db.scalars(stmt.order_by(Invoice.created_at.desc(), Invoice.id.desc())
                      .offset((page - 1) * size).limit(size)).unique().all()
    pending_cancel = db.scalar(select(func.count(Invoice.id)).where(
        Invoice.cancel_requested_at.is_not(None), Invoice.status == "paid")) if user.role != "staff" else None
    return {"total": total, "sum_paid": int(sum_total), "cancel_requests": pending_cancel,
            "items": [invoice_out(i, False) for i in rows]}


def _get_invoice(db: Session, invoice_id: int, user: User) -> Invoice:
    inv = db.scalar(select(Invoice).options(
        selectinload(Invoice.items).joinedload(InvoiceItem.product),
        selectinload(Invoice.items).joinedload(InvoiceItem.serial),
        selectinload(Invoice.payments), joinedload(Invoice.customer), joinedload(Invoice.promotion))
        .where(Invoice.id == invoice_id))
    if inv is None or (user.role == "staff" and inv.user_id != user.id):
        raise HTTPException(404, "Không tìm thấy hóa đơn")
    return inv


def _out(db: Session, invoice_id: int, user: User, cart=None) -> dict:
    db.expire_all()
    data = invoice_out(_get_invoice(db, invoice_id, user), db=db, user=user)
    if cart is not None:
        data["promotions"] = cart.applied_promotions()
        data["warnings"] = cart.below_cost + cart.warnings
    return data


@router.get("/invoices/{invoice_id}")
def get_invoice(invoice_id: int, db: Session = Depends(get_db), user: User = Depends(ALL_STAFF)):
    _expire(db)
    inv = _get_invoice(db, invoice_id, user)
    data = invoice_out(inv, db=db, user=user)
    data["returns"] = [{"id": r.id, "code": r.code, "refund_amount": r.refund_amount, "created_at": r.created_at}
                       for r in db.scalars(select(Return).where(Return.invoice_id == inv.id))]
    return data


def _run(db: Session, fn, *args, **kwargs):
    """Chạy nghiệp vụ trong một giao dịch; mã hóa đơn trùng do hai quầy lập cùng lúc thì thử lại một lần."""
    for attempt in range(2):
        try:
            lock_for_write(db)  # mã chứng từ không trùng khi nhiều quầy ghi cùng lúc (FR-SAL-12)
            result = fn(*args, **kwargs)
            db.commit()
            return result
        except BusinessError as e:
            db.rollback()
            raise e.http()
        except IntegrityError:
            db.rollback()
            if attempt == 1:
                raise HTTPException(409, "Có quầy khác vừa lập hóa đơn cùng lúc, vui lòng thử lại")
            db.expire_all()


@router.post("/invoices/preview")
def preview_invoice(data: InvoiceIn, db: Session = Depends(get_db), user: User = Depends(ALL_STAFF)):
    """Tính thử giỏ hàng mỗi khi giỏ thay đổi: tạm tính, khuyến mãi được áp, điểm tối đa, VAT, điểm dự kiến."""
    try:
        cart = sales.preview(db, data, user)
    except BusinessError as e:
        raise e.http()
    finally:
        db.rollback()
    return cart.summary()


@router.post("/invoices/drafts", status_code=201)
def save_draft(data: InvoiceIn, db: Session = Depends(get_db), user: User = Depends(ALL_STAFF)):
    """FR-SAL-07: lưu giỏ dạng nháp (draft_id để cập nhật bản nháp đang có)."""
    existing = _get_invoice(db, data.draft_id, user) if data.draft_id else None
    inv, cart = _run(db, sales.save_draft, db, data, user, existing)
    return _out(db, inv.id, user, cart)


@router.post("/invoices", status_code=201)
def create_invoice(data: InvoiceIn, db: Session = Depends(get_db), user: User = Depends(ALL_STAFF)):
    _expire(db)
    existing = _get_invoice(db, data.draft_id, user) if data.draft_id else None
    if existing is not None and existing.status != "draft":
        raise HTTPException(400, "Hóa đơn nháp đã được chốt hoặc đã hủy")
    inv, cart = _run(db, lambda: sales.checkout(db, data, user, existing))
    return _out(db, inv.id, user, cart)


@router.put("/invoices/{invoice_id}")
def update_invoice(invoice_id: int, data: InvoiceIn, db: Session = Depends(get_db), user: User = Depends(ALL_STAFF)):
    """FR-SAL-11, BR-24: chỉ sửa hóa đơn nháp hoặc chờ thanh toán; tính lại các khoản và đồng bộ tồn kho."""
    _expire(db)
    inv = _get_invoice(db, invoice_id, user)
    if inv.status == "draft":
        _, cart = _run(db, sales.save_draft, db, data, user, inv)
    else:
        _, cart = _run(db, lambda: sales.checkout(db, data, user, inv))
    return _out(db, invoice_id, user, cart)


@router.post("/invoices/{invoice_id}/cancel")
def cancel_invoice(invoice_id: int, data: InvoiceCancelIn, db: Session = Depends(get_db),
                   user: User = Depends(ALL_STAFF)):
    """Hủy hóa đơn nháp / chờ thanh toán; hóa đơn đã thanh toán: chủ cửa hàng hủy, nhân viên gửi yêu cầu (UC-29)."""
    _expire(db)
    inv = _get_invoice(db, invoice_id, user)
    if inv.status == "paid" and user.role == "staff":
        _run(db, sales.request_cancel, db, inv, data.reason, user)
        return {**_out(db, invoice_id, user), "message": "Đã gửi yêu cầu hủy, chờ chủ cửa hàng duyệt"}
    _run(db, sales.cancel, db, inv, data.reason, user)
    return _out(db, invoice_id, user)


@router.post("/invoices/{invoice_id}/cancel/approve")
def decide_cancel(invoice_id: int, data: CancelDecisionIn, db: Session = Depends(get_db),
                  user: User = Depends(MANAGERS)):
    inv = _get_invoice(db, invoice_id, user)
    _run(db, sales.decide_cancel, db, inv, data.approve, user, data.note)
    return _out(db, invoice_id, user)


@router.post("/invoices/{invoice_id}/confirm-payment")
def confirm_payment(invoice_id: int, data: ConfirmPaymentIn | None = None, db: Session = Depends(get_db),
                    user: User = Depends(ALL_STAFF)):
    """FR-PAY-05: nhân viên xác nhận đã nhận tiền chuyển khoản; ghi người xác nhận và thời điểm."""
    _expire(db)
    inv = _get_invoice(db, invoice_id, user)
    data = data or ConfirmPaymentIn()
    _run(db, sales.confirm_payment, db, inv, user, data.payment_method, data.payment_ref, data.cash_received)
    return _out(db, invoice_id, user)


@router.get("/invoices/{invoice_id}/qr")
def invoice_qr(invoice_id: int, db: Session = Depends(get_db), user: User = Depends(ALL_STAFF)):
    """FR-PAY-03, 04: mã VietQR có sẵn ngân hàng, số tài khoản, số tiền, nội dung là mã hóa đơn; kèm hạn giữ hàng."""
    _expire(db)
    inv = _get_invoice(db, invoice_id, user)
    bank = app_settings.get_many(db, ["bank_bin", "bank_name", "bank_account", "bank_account_name"])
    payload = vietqr_payload(bank["bank_bin"], bank["bank_account"], inv.total, inv.code)
    return {"code": inv.code, "amount": inv.total, "status": inv.status, "payload": payload, "svg": qr_svg(payload),
            "bank_name": bank["bank_name"], "account_no": bank["bank_account"],
            "account_name": bank["bank_account_name"], "content": inv.code.replace("-", ""),
            "deadline": sales.pending_deadline(db, inv)}


def _store(db: Session) -> dict:
    return app_settings.get_many(db, ["store_name", "store_address", "store_phone", "store_tax_code"])


def _invoice_pdf(db: Session, inv: Invoice, reprint: bool) -> bytes:
    warranties = {w.invoice_item_id: w for w in db.scalars(
        select(Warranty).where(Warranty.invoice_item_id.in_([it.id for it in inv.items])))}
    return receipts.invoice_pdf(inv, _store(db), warranties, reprint)


@router.get("/invoices/{invoice_id}/pdf")
def invoice_pdf(invoice_id: int, reprint: bool = False, db: Session = Depends(get_db),
                user: User = Depends(ALL_STAFF)):
    """FR-PAY-07..09: hóa đơn PDF khổ 80 mm; in lại được đánh dấu Bản in lại và ghi audit log."""
    inv = _get_invoice(db, invoice_id, user)
    reprint = reprint or inv.print_count > 0
    content = _invoice_pdf(db, inv, reprint)
    if reprint:
        audit.log(db, user, "INVOICE_REPRINT", "invoices", inv.id, new={"print_count": inv.print_count + 1})
    inv.print_count += 1
    db.commit()
    return Response(content, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{inv.code}.pdf"'})


def _send_invoice_mail(invoice_id: int, to: str, user_id: int) -> None:
    from app.database import SessionLocal
    with SessionLocal() as db:
        inv = db.get(Invoice, invoice_id)
        store = _store(db)
        try:
            send_logged(db, to, f"[{store['store_name']}] Hóa đơn {inv.code}",
                        f"Cảm ơn quý khách đã mua hàng tại {store['store_name']}.\n"
                        f"Hóa đơn {inv.code}, tổng thanh toán {inv.total:,}đ, đính kèm bản PDF.".replace(",", "."),
                        "invoice", [(f"{inv.code}.pdf", _invoice_pdf(db, inv, False), "application/pdf")])
        except MailError:
            pass  # đã ghi email_logs


@router.post("/invoices/{invoice_id}/email")
def email_invoice(invoice_id: int, background: BackgroundTasks, data: EmailInvoiceIn | None = None,
                  db: Session = Depends(get_db), user: User = Depends(ALL_STAFF)):
    """FR-PAY-10: gửi hóa đơn PDF qua email khách, kết quả ghi vào email_logs."""
    inv = _get_invoice(db, invoice_id, user)
    to = (data.email if data else None) or (inv.customer.email if inv.customer else None)
    if not to:
        raise HTTPException(400, "Khách hàng chưa có email")
    if not mail_configured():
        raise HTTPException(503, "Hệ thống chưa cấu hình gửi email")
    background.add_task(_send_invoice_mail, inv.id, to, user.id)
    return {"ok": True, "message": f"Đang gửi hóa đơn tới {to}"}


# ---------------- Phiếu nhập kiểu cũ (giữ cho client cũ; bản mới dùng /api/purchase-orders) ----------------
def import_out(r: ImportReceipt, with_items: bool = True) -> dict:
    data = {"id": r.id, "code": r.code, "supplier": r.supplier, "supplier_id": r.supplier_id, "status": r.status,
            "note": r.note, "total": r.total, "created_at": r.created_at, "user_name": r.user.full_name,
            "item_count": len(r.items)}
    if with_items:
        data["items"] = [{"product_id": it.product_id, "product_code": it.product.code,
                          "product_name": it.product.name, "quantity": it.quantity,
                          "unit_cost": it.unit_cost, "line_total": it.line_total} for it in r.items]
    return data


@router.get("/imports")
def list_imports(date_from: str | None = None, date_to: str | None = None, q: str | None = None,
                 page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=200),
                 db: Session = Depends(get_db), _: User = Depends(MANAGERS)):
    stmt = select(ImportReceipt).options(joinedload(ImportReceipt.user), selectinload(ImportReceipt.items))
    if date_from or date_to:
        start, end = parse_range(date_from, date_to)
        stmt = stmt.where(ImportReceipt.created_at >= start, ImportReceipt.created_at < end)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(ImportReceipt.code.ilike(like), ImportReceipt.supplier.ilike(like)))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(ImportReceipt.created_at.desc(), ImportReceipt.id.desc())
                      .offset((page - 1) * size).limit(size)).unique().all()
    return {"total": total, "items": [import_out(r, False) for r in rows]}


@router.get("/imports/{receipt_id}")
def get_import(receipt_id: int, db: Session = Depends(get_db), _: User = Depends(MANAGERS)):
    r = db.get(ImportReceipt, receipt_id)
    if r is None:
        raise HTTPException(404, "Không tìm thấy phiếu nhập")
    return import_out(r)


@router.post("/imports", status_code=201)
def create_import(data: ImportIn, db: Session = Depends(get_db), user: User = Depends(MANAGERS)):
    try:
        r = inventory.create_import(db, data, user)
        db.commit()
    except BusinessError as e:
        db.rollback()
        raise e.http()
    return import_out(r)
