"""Đổi trả hàng (UC-31) và bảo hành (UC-32 đến UC-34)."""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.database import get_db, lock_for_write
from app.models import Customer, Invoice, InvoiceItem, Return, ReturnItem, User, Warranty, WarrantyTicket, now
from app.schemas import ReturnIn, TicketIn, TicketUpdateIn
from app.security import ALL_STAFF
from app.services import aftersales, app_settings, receipts
from app.services.inventory import BusinessError
from app.services.mailer import MailError, mail_configured, send_logged
from app.services.reports import parse_range

router = APIRouter(prefix="/api", tags=["aftersales"])


def _commit(db: Session, fn, *args):
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
        raise HTTPException(409, "Có thao tác khác vừa ghi cùng lúc, vui lòng thử lại")


def _store(db: Session) -> dict:
    return app_settings.get_many(db, ["store_name", "store_address", "store_phone", "store_tax_code"])


# ---------------------------------------------------------------- Đổi trả
def _load_invoice(db: Session, invoice_id: int) -> Invoice:
    inv = db.scalar(select(Invoice).options(selectinload(Invoice.items).joinedload(InvoiceItem.product),
                                            selectinload(Invoice.items).joinedload(InvoiceItem.serial),
                                            joinedload(Invoice.customer)).where(Invoice.id == invoice_id))
    if inv is None:
        raise HTTPException(404, "Không tìm thấy hóa đơn")
    return inv


@router.get("/returns/lookup")
def lookup_invoices(q: str = Query(min_length=3), db: Session = Depends(get_db), _: User = Depends(ALL_STAFF)):
    """FR-RET-01: tra hóa đơn đổi trả theo mã hóa đơn hoặc số điện thoại khách."""
    key = q.strip().upper().replace(" ", "")
    stmt = select(Invoice).outerjoin(Customer).where(or_(Invoice.code == key, Invoice.code.like(f"%{key}%"),
                                                         Customer.phone == key))
    rows = db.scalars(stmt.where(Invoice.status.in_(("paid", "partially_returned", "fully_returned")))
                      .order_by(Invoice.paid_at.desc()).limit(20)).unique().all()
    return [aftersales.eligibility(db, _load_invoice(db, inv.id)) for inv in rows]


@router.get("/returns/eligible/{invoice_id}")
def eligible(invoice_id: int, db: Session = Depends(get_db), _: User = Depends(ALL_STAFF)):
    return aftersales.eligibility(db, _load_invoice(db, invoice_id))


def _load_return(db: Session, return_id: int) -> Return:
    r = db.scalar(select(Return).options(
        selectinload(Return.items).joinedload(ReturnItem.invoice_item).joinedload(InvoiceItem.product),
        joinedload(Return.invoice).joinedload(Invoice.customer), joinedload(Return.new_invoice),
        joinedload(Return.user)).where(Return.id == return_id))
    if r is None:
        raise HTTPException(404, "Không tìm thấy phiếu đổi trả")
    return r


@router.get("/returns")
def list_returns(date_from: str | None = None, date_to: str | None = None, q: str | None = None,
                 page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=200),
                 db: Session = Depends(get_db), _: User = Depends(ALL_STAFF)):
    stmt = select(Return).join(Invoice, Return.invoice_id == Invoice.id)
    if date_from or date_to:
        start, end = parse_range(date_from, date_to)
        stmt = stmt.where(Return.created_at >= start, Return.created_at < end)
    if q:
        like = f"%{q.strip().upper()}%"
        stmt = stmt.where(or_(Return.code.like(like), Invoice.code.like(like)))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    refund = db.scalar(select(func.coalesce(func.sum(Return.refund_amount), 0)).where(
        Return.id.in_(stmt.with_only_columns(Return.id))))
    ids = db.scalars(stmt.with_only_columns(Return.id).order_by(Return.id.desc())
                     .offset((page - 1) * size).limit(size)).all()
    return {"total": total, "refund_total": int(refund),
            "items": [aftersales.return_out(_load_return(db, i)) for i in ids]}


@router.get("/returns/{return_id}")
def get_return(return_id: int, db: Session = Depends(get_db), _: User = Depends(ALL_STAFF)):
    return aftersales.return_out(_load_return(db, return_id))


@router.post("/returns", status_code=201)
def create_return(data: ReturnIn, db: Session = Depends(get_db), user: User = Depends(ALL_STAFF)):
    ret = _commit(db, aftersales.create_return, db, data, user)
    db.expire_all()
    return aftersales.return_out(_load_return(db, ret.id))


@router.get("/returns/{return_id}/pdf")
def return_pdf(return_id: int, db: Session = Depends(get_db), _: User = Depends(ALL_STAFF)):
    """FR-RET-08: in phiếu đổi trả."""
    r = _load_return(db, return_id)
    return Response(receipts.return_pdf(r, _store(db)), media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{r.code}.pdf"'})


# ---------------------------------------------------------------- Bảo hành
@router.get("/warranties/lookup")
def warranty_lookup(q: str = Query(min_length=3), db: Session = Depends(get_db), _: User = Depends(ALL_STAFF)):
    rows = aftersales.lookup(db, q)
    db.commit()
    return [aftersales.warranty_out(db, w) for w in rows]


def _load_ticket(db: Session, ticket_id: int) -> WarrantyTicket:
    t = db.scalar(select(WarrantyTicket).options(
        joinedload(WarrantyTicket.warranty).joinedload(Warranty.product),
        joinedload(WarrantyTicket.warranty).joinedload(Warranty.serial),
        joinedload(WarrantyTicket.warranty).joinedload(Warranty.customer),
        joinedload(WarrantyTicket.user)).where(WarrantyTicket.id == ticket_id))
    if t is None:
        raise HTTPException(404, "Không tìm thấy phiếu bảo hành")
    return t


@router.get("/warranty-tickets")
def list_tickets(status: str | None = None, q: str | None = None, open_only: bool = False,
                 page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=200),
                 db: Session = Depends(get_db), _: User = Depends(ALL_STAFF)):
    stmt = select(WarrantyTicket.id).join(Warranty)
    if status:
        stmt = stmt.where(WarrantyTicket.status == status)
    if open_only:
        stmt = stmt.where(WarrantyTicket.status.in_(("received", "in_repair", "waiting_parts", "done", "rejected")))
    if q:
        like = f"%{q.strip().upper()}%"
        from app.models import ProductSerial
        stmt = stmt.outerjoin(ProductSerial, Warranty.serial_id == ProductSerial.id).where(
            or_(WarrantyTicket.code.like(like), ProductSerial.serial_no.like(like)))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    ids = db.scalars(stmt.order_by(WarrantyTicket.id.desc()).offset((page - 1) * size).limit(size)).all()
    counts = dict(db.execute(select(WarrantyTicket.status, func.count(WarrantyTicket.id))
                             .group_by(WarrantyTicket.status)).all())
    return {"total": total, "counts": counts, "items": [aftersales.ticket_out(_load_ticket(db, i)) for i in ids]}


@router.get("/warranty-tickets/{ticket_id}")
def get_ticket(ticket_id: int, db: Session = Depends(get_db), _: User = Depends(ALL_STAFF)):
    return aftersales.ticket_out(_load_ticket(db, ticket_id))


MAIL_TEXT = {
    "received": "Cửa hàng đã tiếp nhận bảo hành máy {product} (phiếu {code}). Chúng tôi sẽ báo khi có kết quả.",
    "done": "Máy {product} (phiếu {code}) đã sửa xong, mời quý khách đến nhận máy. Kết quả: {resolution}",
    "rejected": "Máy {product} (phiếu {code}) không được bảo hành. Lý do: {resolution}. Mời quý khách đến nhận lại máy.",
}


def _notify(ticket_id: int) -> None:
    """FR-WAR-06, 08: email cho khách khi tiếp nhận, khi sửa xong hoặc từ chối (nếu khách có email)."""
    from app.database import SessionLocal
    with SessionLocal() as db:
        t = db.get(WarrantyTicket, ticket_id)
        customer = t.warranty.customer
        if not customer or not customer.email or t.status not in MAIL_TEXT:
            return
        store = _store(db)
        try:
            send_logged(db, customer.email, f"[{store['store_name']}] Bảo hành {t.code}",
                        MAIL_TEXT[t.status].format(product=t.warranty.product.name, code=t.code,
                                                   resolution=t.resolution or ""), "warranty")
        except MailError:
            pass  # đã ghi email_logs


@router.post("/warranty-tickets", status_code=201)
def create_ticket(data: TicketIn, background: BackgroundTasks, db: Session = Depends(get_db),
                  user: User = Depends(ALL_STAFF)):
    t = _commit(db, aftersales.create_ticket, db, data.warranty_id, data.issue_description.strip(), user)
    if mail_configured():
        background.add_task(_notify, t.id)
    return aftersales.ticket_out(_load_ticket(db, t.id))


@router.put("/warranty-tickets/{ticket_id}")
def update_ticket(ticket_id: int, data: TicketUpdateIn, background: BackgroundTasks, db: Session = Depends(get_db),
                  user: User = Depends(ALL_STAFF)):
    t = _load_ticket(db, ticket_id)
    old = t.status
    _commit(db, aftersales.update_ticket, db, t, data.status, data.resolution, user)
    if t.status != old and t.status in ("done", "rejected") and mail_configured():
        background.add_task(_notify, t.id)
    return aftersales.ticket_out(_load_ticket(db, ticket_id))


@router.get("/warranty-tickets/{ticket_id}/pdf")
def ticket_pdf(ticket_id: int, db: Session = Depends(get_db), _: User = Depends(ALL_STAFF)):
    """FR-WAR-05: in biên nhận bảo hành."""
    t = _load_ticket(db, ticket_id)
    return Response(receipts.warranty_ticket_pdf(t, _store(db)), media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{t.code}.pdf"'})
