from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import PAID_STATES, Branch, Invoice, Product, User, now
from app.routers.invoices import invoice_query
from app.security import ALL_STAFF_VIEW, MANAGERS_VIEW
from app.services import branch_scope, export, reports

router = APIRouter(prefix="/api/reports", tags=["reports"])
STATUS_VI = {"draft": "Nháp", "pending_payment": "Chờ thanh toán", "paid": "Đã thanh toán",
             "partially_returned": "Trả một phần", "fully_returned": "Đã trả hết", "cancelled": "Đã hủy"}
PAY_VI = {"cash": "Tiền mặt", "bank_transfer": "Chuyển khoản", "card": "Quẹt thẻ"}
MAX_EXPORT_ROWS = 50_000  # FR-EXP-04


def _range(date_from, date_to):
    try:
        return reports.parse_range(date_from, date_to)
    except ValueError:
        raise HTTPException(400, "Ngày không hợp lệ, dùng định dạng YYYY-MM-DD")


def _with_images(db: Session, rows: list[dict]) -> list[dict]:
    """Gắn ảnh sản phẩm cho các bảng trên giao diện. Làm ở đây (không trong services.reports)
    để dữ liệu thống kê gửi cho AI không kèm đường dẫn ảnh thừa."""
    urls = dict(db.execute(select(Product.code, Product.image_url)
                           .where(Product.code.in_([r["code"] for r in rows]))).all())
    return [{**r, "image_url": urls.get(r["code"])} for r in rows]


def _by_branch(db: Session, start: datetime, end: datetime) -> list[dict]:
    """Doanh thu từng chi nhánh khi chi nhánh chính xem mọi chi nhánh (kể cả chi nhánh chưa bán được gì)."""
    if not branch_scope.viewing_all(db):
        return []
    rows = reports.revenue_by_branch(db, start, end)
    seen = {r["branch_id"] for r in rows}
    zero = {"invoice_count": 0, "gross_sales": 0, "refunds": 0, "vat": 0, "cost": 0, "revenue": 0,
            "revenue_net": 0, "gross_profit": 0}
    rows += [{"branch_id": b.id, "branch_name": b.name, **zero}
             for b in db.scalars(select(Branch).where(Branch.is_active.is_(True)).order_by(Branch.id)) if b.id not in seen]
    return rows


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db), user: User = Depends(MANAGERS_VIEW)):
    d = reports.dashboard(db)
    if branch_scope.viewing_other(db):
        # "Việc cần xử lý" luôn là việc của chi nhánh mình: hóa đơn chi nhánh khác chỉ xem, không xử lý được
        own = Invoice.branch_id == user.branch_id
        d["pending_payment"] = db.scalar(select(func.count(Invoice.id)).where(
            own, Invoice.status == "pending_payment").execution_options(**branch_scope.ALL_BRANCHES))
        d["cancel_requests"] = db.scalar(select(func.count(Invoice.id)).where(
            own, Invoice.cancel_requested_at.is_not(None), Invoice.status == "paid")
            .execution_options(**branch_scope.ALL_BRANCHES))
    d["top_products_30"] = _with_images(db, d["top_products_30"])
    d["low_stock"] = _with_images(db, d["low_stock"])
    today = now().date()
    d["by_branch_month"] = _by_branch(db, datetime(today.year, today.month, 1), reports.parse_range(today, today)[1])
    d["date"] = today.isoformat()  # để liên kết sang trang Hóa đơn đúng ngày máy chủ đang tính
    return d


@router.get("/revenue")
def revenue(date_from: str | None = None, date_to: str | None = None,
            db: Session = Depends(get_db), _: User = Depends(MANAGERS_VIEW)):
    start, end = _range(date_from, date_to)
    return {
        "summary": reports.revenue_total(db, start, end),
        "by_day": reports.revenue_by_day(db, start, end),
        "by_category": reports.revenue_by_category(db, start, end),
        "top_products": _with_images(db, reports.top_products(db, start, end, 10)),
        "slow_products": _with_images(db, reports.slow_products(db, start, end, 10)),
        "by_branch": _by_branch(db, start, end),
    }


@router.get("/monthly")
def monthly(year: int = Query(default_factory=lambda: now().year, ge=2000, le=2100),
            db: Session = Depends(get_db), _: User = Depends(MANAGERS_VIEW)):
    return reports.revenue_by_month(db, year)


@router.get("/top-products")
def top_products(date_from: str | None = None, date_to: str | None = None,
                 by: str = Query("quantity", pattern="^(quantity|revenue)$"), limit: int = Query(10, ge=1, le=100),
                 db: Session = Depends(get_db), _: User = Depends(MANAGERS_VIEW)):
    start, end = _range(date_from, date_to)
    return {"top": _with_images(db, reports.top_products(db, start, end, limit, by)),
            "slow": _with_images(db, reports.slow_products(db, start, end, limit)),
            "by_product": reports.revenue_by_product(db, start, end)}


@router.get("/inventory")
def inventory_report(db: Session = Depends(get_db), _: User = Depends(MANAGERS_VIEW)):
    return reports.inventory_report(db)


@router.get("/low-stock")
def low_stock(db: Session = Depends(get_db), _: User = Depends(MANAGERS_VIEW)):
    return _with_images(db, reports.low_stock(db))


def _file(content: bytes, fmt: str, name: str) -> Response:
    return Response(content, media_type=export.MEDIA[fmt],
                    headers={"Content-Disposition": f'attachment; filename="{name}.{fmt}"'})


@router.get("/export/revenue")
def export_revenue(format: str = Query("xlsx", pattern="^(csv|xlsx|pdf)$"),
                   date_from: str | None = None, date_to: str | None = None,
                   db: Session = Depends(get_db), _: User = Depends(MANAGERS_VIEW)):
    start, end = _range(date_from, date_to)
    s = reports.revenue_total(db, start, end)
    by_day = reports.revenue_by_day(db, start, end)
    by_cat = reports.revenue_by_category(db, start, end)
    top = reports.top_products(db, start, end, 10)
    period = f"{start.date()} đến {(end - timedelta(days=1)).date()}"
    day_rows = [[d["date"], d["invoice_count"], d["revenue"]] for d in by_day]
    cat_rows = [[c["category"], c["quantity"], c["revenue"]] for c in by_cat]
    top_rows = [[p["code"], p["name"], p["quantity"], p["revenue"]] for p in top]
    branch_rows = [[b["branch_name"], b["invoice_count"], b["revenue"], b["gross_profit"]]
                   for b in _by_branch(db, start, end)]
    branch_head = ["Chi nhánh", "Số hóa đơn", "Doanh thu", "Lãi gộp"]
    name = f"bao_cao_doanh_thu_{start.date()}_{end.date()}"
    if branch_rows:
        name += "_tat_ca_chi_nhanh"
        period += " - tất cả chi nhánh"

    if format == "csv":
        return _file(export.to_csv(["Ngày", "Số hóa đơn", "Doanh thu"], day_rows), "csv", name)
    if format == "xlsx":
        summary_rows = [["Kỳ báo cáo", period], ["Số hóa đơn", s["invoice_count"]], ["Doanh số", s["gross_sales"]],
                        ["Tiền hoàn đổi trả", s["refunds"]], ["Doanh thu (gồm VAT)", s["revenue"]],
                        ["VAT", s["vat"]], ["Doanh thu chưa VAT", s["revenue_net"]], ["Giảm giá", s["discount"]],
                        ["Giá vốn", s["cost"]], ["Lãi gộp", s["gross_profit"]]]
        return _file(export.to_xlsx([
            ("Tổng quan", ["Chỉ tiêu", "Giá trị"], summary_rows),
            ("Theo ngày", ["Ngày", "Số hóa đơn", "Doanh thu"], day_rows),
            ("Theo nhóm hàng", ["Nhóm hàng", "Số lượng", "Doanh thu"], cat_rows),
            ("Bán chạy", ["Mã", "Sản phẩm", "Số lượng", "Doanh thu"], top_rows),
        ] + ([("Theo chi nhánh", branch_head, branch_rows)] if branch_rows else [])), "xlsx", name)
    v = export.vnd
    return _file(export.to_pdf(
        "BÁO CÁO DOANH THU", f"Kỳ: {period}",
        [
            ("Tổng quan", ["Chỉ tiêu", "Giá trị"], [
                ["Số hóa đơn", s["invoice_count"]], ["Doanh thu (gồm VAT)", v(s["revenue"])],
                ["Tiền hoàn đổi trả", v(s["refunds"])], ["Doanh thu chưa VAT", v(s["revenue_net"])],
                ["Giá vốn", v(s["cost"])], ["Lãi gộp", v(s["gross_profit"])]], [1, 1]),
        ] + ([("Doanh thu theo chi nhánh", branch_head, [[r[0], r[1], v(r[2]), v(r[3])] for r in branch_rows],
               [3, 1, 2, 2])] if branch_rows else []) + [
            ("Doanh thu theo nhóm hàng", ["Nhóm hàng", "Số lượng", "Doanh thu"],
             [[r[0], r[1], v(r[2])] for r in cat_rows], [3, 1, 2]),
            ("Top sản phẩm bán chạy", ["Mã", "Sản phẩm", "SL", "Doanh thu"],
             [[r[0], r[1], r[2], v(r[3])] for r in top_rows], [1.2, 4, 0.8, 2]),
            ("Doanh thu theo ngày", ["Ngày", "Số HĐ", "Doanh thu"],
             [[r[0], r[1], v(r[2])] for r in day_rows if r[1]], [2, 1, 2]),
        ],
    ), "pdf", name)


@router.get("/export/invoices")
def export_invoices(format: str = Query("xlsx", pattern="^(csv|xlsx|pdf)$"),
                    q: str | None = None, status: str | None = None, payment_method: str | None = None,
                    date_from: str | None = None, date_to: str | None = None,
                    db: Session = Depends(get_db), user: User = Depends(ALL_STAFF_VIEW)):
    """FR-EXP-01..04: xuất theo đúng bộ lọc đang áp dụng; nhân viên chỉ xuất hóa đơn do mình lập."""
    _range(date_from, date_to)
    stmt = invoice_query(user, q, status, date_from, date_to, payment_method, None)
    stmt = stmt.options(joinedload(Invoice.customer), joinedload(Invoice.user))
    invoices = db.scalars(stmt.order_by(Invoice.created_at.desc()).limit(MAX_EXPORT_ROWS)).unique().all()
    headers = ["Mã HĐ", "Thời gian", "Khách hàng", "Nhân viên", "Tạm tính", "Giảm giá", "Tổng tiền",
               "Thanh toán", "Trạng thái"]
    rows = [[i.code, i.created_at.strftime("%Y-%m-%d %H:%M"), i.customer.name if i.customer else "Khách lẻ",
             i.user.full_name, i.subtotal, i.discount, i.total, PAY_VI.get(i.payment_method, i.payment_method),
             STATUS_VI.get(i.status, i.status)] for i in invoices]
    if branch_scope.viewing_other(db):  # chi nhánh chính xuất hóa đơn chi nhánh khác: thêm cột chi nhánh
        names = dict(db.execute(select(Branch.id, Branch.name)).all())
        headers.append("Chi nhánh")
        for i, r in zip(invoices, rows):
            r.append(names.get(i.branch_id, ""))
    name = f"danh_sach_hoa_don_{date_from or 'tat-ca'}_{date_to or now().date()}"
    if format == "csv":
        return _file(export.to_csv(headers, rows), "csv", name)
    if format == "xlsx":
        return _file(export.to_xlsx([("Hóa đơn", headers, rows)]), "xlsx", name)
    v = export.vnd
    total = sum(i.total for i in invoices if i.status in PAID_STATES)
    pdf_rows = [[r[0], r[1], r[2], v(r[6]), r[7], r[8]] for r in rows]
    return _file(export.to_pdf(
        "DANH SÁCH HÓA ĐƠN", f"{len(rows)} hóa đơn - tổng đã thanh toán {v(total)} đ",
        [("Chi tiết", ["Mã HĐ", "Thời gian", "Khách hàng", "Tổng tiền", "Thanh toán", "Trạng thái"],
          pdf_rows, [1.6, 1.6, 2.2, 1.3, 1.3, 1.3])],
    ), "pdf", name)


# SRS bảng 8.10 đặt API xuất file ở /api/export/*; giữ /api/reports/export/* cho giao diện cũ
export_router = APIRouter(prefix="/api/export", tags=["reports"])
export_router.get("/revenue")(export_revenue)
export_router.get("/invoices")(export_invoices)
