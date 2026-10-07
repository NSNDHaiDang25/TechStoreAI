"""Truy vấn thống kê doanh thu, tồn kho, sản phẩm bán chạy / bán chậm (SRS 5.15).

- Doanh thu tính theo ngày thanh toán (paid_at) của hóa đơn đã thanh toán, kể cả hóa đơn đã trả một phần
  hoặc toàn bộ; tiền hoàn của đổi trả trừ vào doanh thu của ngày đổi trả (FR-RPT-06).
- Lợi nhuận gộp = doanh thu chưa VAT - giá vốn tại lúc bán (FR-RPT-05).
Nhóm theo ngày/tháng làm ở Python để chạy giống nhau trên SQLite, MySQL, PostgreSQL.
"""
from collections import OrderedDict, defaultdict
from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (PAID_STATES, Category, Customer, Invoice, InvoiceItem, Product, Return, ReturnItem, now)


def parse_range(date_from: str | date | None, date_to: str | date | None,
                default_days: int = 30) -> tuple[datetime, datetime]:
    """Trả về [start, end) theo ngày. Mặc định: 30 ngày gần nhất tính cả hôm nay."""
    def to_date(v):
        if v is None or v == "":
            return None
        return v if isinstance(v, date) else date.fromisoformat(v)

    d_to = to_date(date_to) or now().date()
    d_from = to_date(date_from) or d_to - timedelta(days=default_days - 1)
    if d_from > d_to:
        d_from, d_to = d_to, d_from
    return datetime.combine(d_from, time.min), datetime.combine(d_to + timedelta(days=1), time.min)


def _paid_in(start: datetime, end: datetime):
    return (Invoice.status.in_(PAID_STATES), Invoice.paid_at >= start, Invoice.paid_at < end)


def _returns_in(db: Session, start: datetime, end: datetime) -> list[tuple]:
    """(ngày đổi trả, số lượng trả, tiền hoàn, giá vốn, VAT, dòng hóa đơn) cho mỗi dòng trả trong kỳ."""
    rows = db.execute(
        select(Return.created_at, ReturnItem.quantity, ReturnItem.refund_amount, InvoiceItem)
        .join(ReturnItem, ReturnItem.return_id == Return.id).join(InvoiceItem, ReturnItem.invoice_item_id == InvoiceItem.id)
        .where(Return.created_at >= start, Return.created_at < end)).all()
    out = []
    for at, qty, refund, it in rows:
        vat = it.vat_amount * qty // it.quantity if it.quantity else 0
        out.append((at, qty, refund, it.unit_cost * qty, vat, it))
    return out


def revenue_total(db: Session, start: datetime, end: datetime) -> dict:
    row = db.execute(
        select(func.count(Invoice.id), func.coalesce(func.sum(Invoice.total), 0),
               func.coalesce(func.sum(Invoice.discount), 0), func.coalesce(func.sum(Invoice.vat_amount), 0))
        .where(*_paid_in(start, end))
    ).one()
    cost = db.scalar(
        select(func.coalesce(func.sum(InvoiceItem.unit_cost * InvoiceItem.quantity), 0))
        .join(Invoice).where(*_paid_in(start, end))
    )
    returns = _returns_in(db, start, end)
    refunds = sum(r[2] for r in returns)
    revenue = int(row[1]) - refunds
    vat = int(row[3]) - sum(r[4] for r in returns)
    cost = int(cost) - sum(r[3] for r in returns)
    return {
        "invoice_count": row[0], "gross_sales": int(row[1]), "refunds": refunds, "revenue": revenue,
        "discount": int(row[2]), "vat": vat, "revenue_net": revenue - vat, "cost": cost,
        "gross_profit": revenue - vat - cost,
    }


def revenue_by_day(db: Session, start: datetime, end: datetime) -> list[dict]:
    buckets: OrderedDict[str, dict] = OrderedDict()
    d = start.date()
    while d < end.date():
        buckets[d.isoformat()] = {"date": d.isoformat(), "revenue": 0, "invoice_count": 0}
        d += timedelta(days=1)
    for paid_at, total in db.execute(select(Invoice.paid_at, Invoice.total).where(*_paid_in(start, end))):
        b = buckets[paid_at.date().isoformat()]
        b["revenue"] += total
        b["invoice_count"] += 1
    for r in _returns_in(db, start, end):
        buckets[r[0].date().isoformat()]["revenue"] -= r[2]
    return list(buckets.values())


def revenue_by_month(db: Session, year: int) -> list[dict]:
    start, end = datetime(year, 1, 1), datetime(year + 1, 1, 1)
    months = [{"month": f"{year}-{m:02d}", "revenue": 0, "invoice_count": 0} for m in range(1, 13)]
    for paid_at, total in db.execute(select(Invoice.paid_at, Invoice.total).where(*_paid_in(start, end))):
        months[paid_at.month - 1]["revenue"] += total
        months[paid_at.month - 1]["invoice_count"] += 1
    for r in _returns_in(db, start, end):
        months[r[0].month - 1]["revenue"] -= r[2]
    return months


def _sold_lines(db: Session, start: datetime, end: datetime) -> list[tuple]:
    """(sản phẩm, nhóm, số lượng giữ lại, doanh thu giữ lại) mỗi dòng bán trong kỳ, đã trừ phần khách trả."""
    rows = db.execute(
        select(InvoiceItem, Product.code, Product.name, Product.stock, func.coalesce(Category.name, "Chưa phân nhóm"))
        .join(Invoice).join(Product).outerjoin(Category, Product.category_id == Category.id)
        .where(*_paid_in(start, end))).all()
    out = []
    for it, code, name, stock, cat in rows:
        kept = it.quantity - it.returned_qty
        revenue = it.net_total * kept // it.quantity if it.quantity else 0
        out.append((code, name, stock, cat, kept, revenue))
    return out


def revenue_by_category(db: Session, start: datetime, end: datetime) -> list[dict]:
    agg: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for _, _, _, cat, qty, revenue in _sold_lines(db, start, end):
        agg[cat][0] += qty
        agg[cat][1] += revenue
    rows = sorted(agg.items(), key=lambda x: -x[1][1])
    return [{"category": c, "quantity": q, "revenue": r} for c, (q, r) in rows]


def revenue_by_product(db: Session, start: datetime, end: datetime) -> list[dict]:
    agg: dict[str, dict] = {}
    for code, name, stock, cat, qty, revenue in _sold_lines(db, start, end):
        a = agg.setdefault(code, {"code": code, "name": name, "category": cat, "stock": stock,
                                  "quantity": 0, "revenue": 0})
        a["quantity"] += qty
        a["revenue"] += revenue
    return list(agg.values())


def top_products(db: Session, start: datetime, end: datetime, limit: int = 10, by: str = "quantity") -> list[dict]:
    """FR-RPT-04: bán chạy theo số lượng (mặc định) hoặc doanh thu."""
    rows = [r for r in revenue_by_product(db, start, end) if r["quantity"] > 0]
    key = (lambda r: (-r["revenue"], -r["quantity"])) if by == "revenue" else (lambda r: (-r["quantity"], -r["revenue"]))
    return [{k: r[k] for k in ("code", "name", "stock", "quantity", "revenue")} for r in sorted(rows, key=key)[:limit]]


def slow_products(db: Session, start: datetime, end: datetime, limit: int = 10) -> list[dict]:
    """Sản phẩm đang kinh doanh, còn tồn nhưng bán ít nhất trong kỳ (kể cả bán 0)."""
    sold = {r["code"]: r["quantity"] for r in revenue_by_product(db, start, end)}
    products = db.scalars(select(Product).where(Product.status == "active", Product.stock > 0)).all()
    rows = sorted(products, key=lambda p: (sold.get(p.code, 0), -p.stock, p.code))[:limit]
    return [{"code": p.code, "name": p.name, "stock": p.stock, "quantity": sold.get(p.code, 0)} for p in rows]


def inventory_report(db: Session, days_unsold: int = 30) -> dict:
    """FR-RPT-07: giá trị tồn kho, sản phẩm sắp hết, sản phẩm không bán được trong 30 ngày."""
    since = now() - timedelta(days=days_unsold)
    sold_recent = set(db.scalars(select(InvoiceItem.product_id).join(Invoice)
                                 .where(Invoice.status.in_(PAID_STATES), Invoice.paid_at >= since)).all())
    products = db.scalars(select(Product).where(Product.status != "discontinued").order_by(Product.code)).all()
    by_cat: dict[str, dict] = defaultdict(lambda: {"units": 0, "value_at_cost": 0, "value_at_sale": 0})
    for p in products:
        c = by_cat[p.category.name if p.category else "Chưa phân nhóm"]
        c["units"] += p.stock
        c["value_at_cost"] += p.stock * p.cost_price
        c["value_at_sale"] += p.stock * p.sale_price
    return {
        "summary": {"products": len(products), "units": sum(p.stock for p in products),
                    "value_at_cost": sum(p.stock * p.cost_price for p in products),
                    "value_at_sale": sum(p.stock * p.sale_price for p in products)},
        "by_category": [{"category": k, **v} for k, v in sorted(by_cat.items())],
        "low_stock": low_stock(db),
        "unsold": [{"code": p.code, "name": p.name, "stock": p.stock, "value_at_cost": p.stock * p.cost_price}
                   for p in products if p.stock > 0 and p.id not in sold_recent],
    }


def low_stock(db: Session) -> list[dict]:
    """FR-STK-02: tồn nhỏ hơn ngưỡng cảnh báo của sản phẩm (mặc định low_stock_threshold = 5)."""
    rows = db.scalars(
        select(Product).where(Product.status == "active", Product.stock < Product.min_stock)
        .order_by(Product.stock)
    ).all()
    return [{"code": p.code, "name": p.name, "stock": p.stock, "min_stock": p.min_stock} for p in rows]


def dashboard(db: Session) -> dict:
    today = now().date()
    t_start, t_end = parse_range(today, today)
    m_start = datetime(today.year, today.month, 1)
    last30_start, last30_end = parse_range(None, None, 30)
    return {
        "today": revenue_total(db, t_start, t_end),
        "month": revenue_total(db, m_start, t_end),
        "pending_payment": db.scalar(select(func.count(Invoice.id)).where(Invoice.status == "pending_payment")),
        "cancel_requests": db.scalar(select(func.count(Invoice.id)).where(
            Invoice.cancel_requested_at.is_not(None), Invoice.status == "paid")),
        "customer_count": db.scalar(select(func.count(Customer.id))),
        "product_count": db.scalar(select(func.count(Product.id)).where(Product.status == "active")),
        "low_stock": low_stock(db),
        "daily_30": revenue_by_day(db, last30_start, last30_end),
        "top_products_30": top_products(db, last30_start, last30_end, 5),
    }


def ai_data_context(db: Session, start: datetime, end: datetime) -> dict:
    """Gói dữ liệu tổng hợp gửi cho AI. Chỉ số liệu kinh doanh, KHÔNG có thông tin cá nhân khách hàng."""
    period_days = (end - start).days
    prev_start = start - timedelta(days=period_days)
    summary, previous = revenue_total(db, start, end), revenue_total(db, prev_start, start)
    # FR-AIR-01: hệ thống tự tính phần so sánh với kỳ trước và giá trị tồn, AI không tự làm phép tính (SRS 6.4)
    growth = round((summary["revenue"] - previous["revenue"]) * 100 / previous["revenue"], 1) \
        if previous["revenue"] else None
    stock_value = int(db.scalar(select(func.coalesce(func.sum(Product.stock * Product.cost_price), 0))
                                .where(Product.status == "active")) or 0)
    return {
        "period": {"from": start.date().isoformat(), "to": (end - timedelta(days=1)).date().isoformat(),
                   "days": period_days},
        "summary": summary,
        "previous_period_summary": previous,
        "comparison": {"revenue_change": summary["revenue"] - previous["revenue"], "growth_percent": growth},
        "stock_value": stock_value,
        "revenue_by_category": revenue_by_category(db, start, end),
        "top_products": top_products(db, start, end, 10),
        "slow_products": slow_products(db, start, end, 10),
        "low_stock": low_stock(db),
        "revenue_by_day": [d for d in revenue_by_day(db, start, end) if d["invoice_count"]],
    }
