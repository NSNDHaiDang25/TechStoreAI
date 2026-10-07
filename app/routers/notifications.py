"""Chuông thông báo trên thanh trên cùng: việc cần chú ý, tính trực tiếp từ dữ liệu theo vai trò.

Trả về dữ liệu có cấu trúc (loại, số lượng, vài tên mẫu, thời điểm mới nhất); giao diện tự ghép câu theo ngôn ngữ đang chọn.
Trạng thái "đã đọc" lưu ở trình duyệt theo chữ ký số lượng + thời điểm, nên khi có việc mới chuông sáng lại.
"""
from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import PAID_STATES, TICKET_OPEN, AILog, ImportReceipt, Invoice, Product, User, WarrantyTicket, now
from app.security import ANY_ROLE

router = APIRouter(prefix="/api", tags=["notifications"])
SAMPLE = 3  # số tên mẫu kèm theo mỗi thông báo
PAYMENT_HOURS = 24  # thông báo đơn hàng đã thanh toán trong khoảng này
PAYMENT_DETAILS = 5


def _item(kind: str, count: int, latest=None, names: list[str] | None = None) -> dict:
    return {"type": kind, "count": count, "latest_at": latest, "names": names or []}


def _count_latest(db: Session, stmt, at_col):
    sub = stmt.subquery()
    return db.execute(select(func.count(), func.max(sub.c[at_col]))).one()


@router.get("/notifications")
def notifications(db: Session = Depends(get_db), user: User = Depends(ANY_ROLE)):
    items = []
    if user.role in ("owner", "staff"):
        low = db.scalars(select(Product).where(Product.status == "active", Product.stock < Product.min_stock)
                         .order_by(Product.stock, Product.name)).all()
        if low:
            items.append(_item("low_stock", len(low), None, [f"{p.name} ({p.stock})" for p in low[:SAMPLE]]))

        # Đơn hàng vừa thanh toán (tiền mặt, thẻ, chuyển khoản đã xác nhận): mỗi lần có đơn mới chuông sáng lại
        paid = select(Invoice.code, Invoice.paid_at).where(
            Invoice.status.in_(PAID_STATES), Invoice.paid_at >= now() - timedelta(hours=PAYMENT_HOURS))
        if user.role == "staff":
            paid = paid.where(Invoice.user_id == user.id)
        n, latest = _count_latest(db, paid, "paid_at")
        if n:
            amount = db.scalar(paid.with_only_columns(func.coalesce(func.sum(Invoice.total), 0)).order_by(None))
            recent = db.execute(paid.with_only_columns(Invoice.code, Invoice.total, Invoice.payment_method, Invoice.paid_at)
                                .order_by(Invoice.paid_at.desc(), Invoice.id.desc()).limit(PAYMENT_DETAILS)).all()
            item = _item("payments", n, latest, [r.code for r in recent])
            item["amount"] = amount
            item["details"] = [{"code": r.code, "total": r.total, "method": r.payment_method, "paid_at": r.paid_at}
                               for r in recent]
            items.append(item)

        pending = select(Invoice.code, Invoice.created_at).where(Invoice.status == "pending_payment")
        if user.role == "staff":  # nhân viên chỉ thấy hóa đơn do mình lập (bảng 4.2)
            pending = pending.where(Invoice.user_id == user.id)
        n, latest = _count_latest(db, pending, "created_at")
        if n:
            codes = db.scalars(pending.with_only_columns(Invoice.code).order_by(Invoice.created_at.desc()).limit(SAMPLE)).all()
            items.append(_item("pending_payment", n, latest, codes))

        tickets = select(WarrantyTicket.code, WarrantyTicket.received_at).where(WarrantyTicket.status.in_(TICKET_OPEN))
        n, latest = _count_latest(db, tickets, "received_at")
        if n:
            items.append(_item("warranty_open", n, latest))

        drafts = select(ImportReceipt.code, ImportReceipt.created_at).where(ImportReceipt.status == "draft")
        n, latest = _count_latest(db, drafts, "created_at")
        if n:
            items.append(_item("draft_receipts", n, latest))

    if user.role == "owner":
        cancel = select(Invoice.code, Invoice.cancel_requested_at).where(
            Invoice.cancel_requested_at.is_not(None), Invoice.status == "paid")
        n, latest = _count_latest(db, cancel, "cancel_requested_at")
        if n:
            codes = db.scalars(cancel.with_only_columns(Invoice.code)
                               .order_by(Invoice.cancel_requested_at.desc()).limit(SAMPLE)).all()
            items.append(_item("cancel_requests", n, latest, codes))

    if user.role == "admin":
        waiting = select(User.full_name, User.created_at).where(User.pending.is_(True))
        n, latest = _count_latest(db, waiting, "created_at")
        if n:
            names = db.scalars(waiting.with_only_columns(User.full_name).order_by(User.created_at.desc()).limit(SAMPLE)).all()
            items.append(_item("pending_users", n, latest, names))

        locked = select(User.full_name, User.locked_until).where(User.locked_until > now())
        n, latest = _count_latest(db, locked, "locked_until")
        if n:
            items.append(_item("locked_users", n, latest,
                               db.scalars(locked.with_only_columns(User.full_name).limit(SAMPLE)).all()))

        ai_failed = select(AILog.id, AILog.created_at).where(
            AILog.status.in_(("error", "timeout")), AILog.created_at >= now() - timedelta(hours=24))
        n, latest = _count_latest(db, ai_failed, "created_at")
        if n:
            items.append(_item("ai_errors", n, latest))
    return {"items": items}
