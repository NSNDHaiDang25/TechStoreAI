"""Hỏi đáp dữ liệu bằng text-to-SQL (SRS 6.5, FR-AIQ-02..08) và năm lớp bảo vệ (bảng 6.6).

Lớp 1  chỉ chủ cửa hàng gọi được /api/ai/ask (kiểm ở router).
Lớp 2  AI chỉ được biết lược đồ các view v_ai_* (VIEW_SCHEMA); view đã bỏ cột nhạy cảm.
Lớp 3  validate_sql(): đúng một câu SELECT, không bình luận, không dấu chấm phẩy giữa câu,
       chỉ đọc view v_ai_*, cấm từ khóa ghi / PRAGMA / ATTACH và hàm hệ thống.
Lớp 4  run_sql(): chạy trên kết nối SQLite chỉ đọc (mode=ro) và PRAGMA query_only = ON.
Lớp 5  run_sql(): tự bọc LIMIT 200 và dừng câu lệnh sau 5 giây bằng set_progress_handler.

Các view viết theo cú pháp SQLite (CSDL mặc định, SRS 2.6). Với CSDL khác, service.ask_data
dùng cách cũ: hệ thống tự tổng hợp số liệu rồi gửi cho AI, không chạy SQL do AI sinh.
"""
import re
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.orm import Session

MAX_ROWS = 200          # FR-AIQ-05
TIMEOUT_SECONDS = 5.0   # FR-AIQ-05

# Giờ Việt Nam cố định UTC+7 (không có giờ mùa hè), paid_at lưu theo giờ cửa hàng
_TODAY = "date('now', '+7 hours')"

# Thứ tự quan trọng: view sau được dựng từ view trước
VIEWS: dict[str, str] = {
    "v_ai_products": """
        SELECT p.code AS sku, p.name, c.name AS category, p.brand, p.sale_price, p.cost_price,
               p.stock AS stock_qty, p.min_stock AS min_stock_level, p.status
        FROM products p LEFT JOIN categories c ON c.id = p.category_id
        WHERE p.status = 'active'""",
    "v_ai_sales_lines": """
        SELECT i.code AS invoice_code, date(i.paid_at) AS sold_date,
               CAST(strftime('%H', i.paid_at) AS INTEGER) AS sold_hour,
               CAST(strftime('%w', i.paid_at) AS INTEGER) AS sold_weekday,
               p.code AS sku, p.name AS product_name, c.name AS category, p.brand,
               (it.quantity - it.returned_qty) AS quantity,
               CAST(ROUND((it.line_total - it.discount_amount) * 1.0 * (it.quantity - it.returned_qty) / it.quantity) AS INTEGER) AS net_revenue,
               CAST(ROUND(it.vat_amount * 1.0 * (it.quantity - it.returned_qty) / it.quantity) AS INTEGER) AS vat_amount,
               it.unit_cost * (it.quantity - it.returned_qty) AS cost_amount,
               cu.code AS customer_code, t.name AS customer_tier, i.payment_method
        FROM invoice_items it
        JOIN invoices i ON i.id = it.invoice_id
        JOIN products p ON p.id = it.product_id
        LEFT JOIN categories c ON c.id = p.category_id
        LEFT JOIN customers cu ON cu.id = i.customer_id
        LEFT JOIN customer_tiers t ON t.id = cu.tier_id
        WHERE i.status IN ('paid', 'partially_returned') AND it.quantity > it.returned_qty""",
    "v_ai_sales_daily": """
        SELECT sold_date, COUNT(DISTINCT invoice_code) AS invoice_count, SUM(net_revenue) AS revenue,
               SUM(vat_amount) AS vat, SUM(net_revenue - vat_amount - cost_amount) AS gross_profit
        FROM v_ai_sales_lines GROUP BY sold_date""",
    "v_ai_inventory": f"""
        SELECT p.code AS sku, p.name, c.name AS category, p.stock AS stock_qty, p.min_stock AS min_stock_level,
               COALESCE((SELECT SUM(s.quantity) FROM v_ai_sales_lines s
                         WHERE s.sku = p.code AND s.sold_date >= date({_TODAY}, '-30 day')), 0) AS sold_30d,
               p.stock * p.cost_price AS stock_value
        FROM products p LEFT JOIN categories c ON c.id = p.category_id
        WHERE p.status = 'active'""",
    "v_ai_purchases": """
        SELECT r.code AS po_code, date(COALESCE(r.received_at, r.created_at)) AS received_date,
               COALESCE(s.name, r.supplier) AS supplier_name, p.code AS sku, p.name AS product_name,
               ii.quantity, ii.unit_cost, ii.line_total
        FROM import_items ii
        JOIN import_receipts r ON r.id = ii.receipt_id
        JOIN products p ON p.id = ii.product_id
        LEFT JOIN suppliers s ON s.id = r.supplier_id
        WHERE r.status = 'confirmed'""",
    "v_ai_returns": """
        SELECT date(r.created_at) AS return_date, r.code AS return_code, i.code AS invoice_code,
               p.code AS sku, p.name AS product_name, ri.quantity, ri.refund_amount, ri.item_condition,
               r.return_type, r.reason
        FROM return_items ri
        JOIN returns r ON r.id = ri.return_id
        JOIN invoice_items it ON it.id = ri.invoice_item_id
        JOIN invoices i ON i.id = r.invoice_id
        JOIN products p ON p.id = it.product_id""",
    "v_ai_customers": """
        SELECT cu.code AS customer_code, t.name AS tier, cu.total_spent, cu.loyalty_points,
               (SELECT COUNT(*) FROM invoices i WHERE i.customer_id = cu.id
                  AND i.status IN ('paid', 'partially_returned', 'fully_returned')) AS order_count,
               (SELECT date(MAX(i.paid_at)) FROM invoices i WHERE i.customer_id = cu.id
                  AND i.status IN ('paid', 'partially_returned', 'fully_returned')) AS last_order_date
        FROM customers cu LEFT JOIN customer_tiers t ON t.id = cu.tier_id
        WHERE cu.is_active = 1""",
}
ALLOWED_VIEWS = frozenset(VIEWS)

# Lược đồ gửi cho AI (lớp 2): chỉ tên view, cột và ý nghĩa
VIEW_SCHEMA = """\
v_ai_products(sku, name, category, brand, sale_price, cost_price, stock_qty, min_stock_level, status)
  -- sản phẩm đang bán; giá tính bằng đồng
v_ai_sales_lines(invoice_code, sold_date, sold_hour, sold_weekday, sku, product_name, category, brand, quantity,
                 net_revenue, vat_amount, cost_amount, customer_code, customer_tier, payment_method)
  -- từng dòng hàng đã bán, đã trừ phần khách trả; sold_date dạng 'YYYY-MM-DD';
  -- sold_weekday: 0 = Chủ nhật ... 6 = Thứ bảy; net_revenue đã trừ giảm giá, đã gồm VAT;
  -- payment_method: cash | bank_transfer | card
v_ai_sales_daily(sold_date, invoice_count, revenue, vat, gross_profit)
  -- doanh thu theo ngày (revenue gồm VAT, gross_profit = revenue - vat - giá vốn)
v_ai_inventory(sku, name, category, stock_qty, min_stock_level, sold_30d, stock_value)
  -- tồn kho, số bán 30 ngày gần nhất, giá trị tồn theo giá vốn
v_ai_purchases(po_code, received_date, supplier_name, sku, product_name, quantity, unit_cost, line_total)
  -- dòng phiếu nhập đã xác nhận
v_ai_returns(return_date, return_code, invoice_code, sku, product_name, quantity, refund_amount, item_condition,
             return_type, reason)
  -- đổi trả; item_condition: sellable | defective; return_type: return | exchange
v_ai_customers(customer_code, tier, total_spent, loyalty_points, order_count, last_order_date)
  -- khách hàng ẩn danh (chỉ có mã KHxxxx, không có tên, số điện thoại, email, địa chỉ)"""


def ensure_views(conn, recreate: bool = False) -> None:
    """Tạo các view v_ai_* (SQLite). recreate=True khi khởi động để cập nhật định nghĩa mới."""
    if conn.dialect.name != "sqlite":
        return
    if recreate:
        for name in reversed(list(VIEWS)):
            conn.execute(text(f"DROP VIEW IF EXISTS {name}"))
    for name, body in VIEWS.items():
        conn.execute(text(f"CREATE VIEW IF NOT EXISTS {name} AS {body}"))


# ---------------------------------------------------------------- Lớp 3: kiểm tra SQL
class SQLRejected(ValueError):
    """SQL vi phạm quy tắc: không chạy, ghi ai_logs trạng thái rejected_sql."""


class SQLTimeout(Exception):
    pass


FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|attach|detach|pragma|create|replace|vacuum|reindex|analyze|"
    r"truncate|grant|revoke|begin|commit|rollback|savepoint|release|upsert|merge|exec|execute)\b", re.I)
SYSTEM_FUNCS = re.compile(
    r"\b(load_extension|readfile|writefile|edit|fts3_tokenizer|zeroblob|randomblob|sqlite_\w+|"
    r"current_setting|pg_\w+)\s*\(|\bsqlite_\w+", re.I)
_STRING = re.compile(r"'(?:[^']|'')*'")
_QUOTED_ID = re.compile(r'"([^"]*)"|`([^`]*)`|\[([^\]]*)\]')
_FROM_JOIN = re.compile(r"\b(?:from|join)\s+([a-z_][\w]*|\()", re.I)
_CTE_NAME = re.compile(r"(?:\bwith\b|,)\s*(?:recursive\s+)?([a-z_]\w*)\s*(?:\([^)]*\))?\s+as\s*\(", re.I)
_FROM_LIST = re.compile(r"\bfrom\s+([a-z_]\w*(?:\s+(?:as\s+)?[a-z_]\w*)?(?:\s*,\s*[a-z_]\w*(?:\s+(?:as\s+)?[a-z_]\w*)?)+)", re.I)


def _base_tables() -> frozenset[str]:
    from app.database import Base
    return frozenset(Base.metadata.tables)


def validate_sql(sql: str) -> str:
    """Trả về câu SQL đã chuẩn hóa (bỏ dấu ; cuối) hoặc ném SQLRejected kèm lý do tiếng Việt."""
    if not sql or not sql.strip():
        raise SQLRejected("AI không sinh được câu truy vấn")
    s = sql.strip()
    if s.startswith("```"):
        s = re.sub(r"^```\w*\s*|\s*```$", "", s).strip()
    s = s.rstrip().rstrip(";").rstrip()
    if len(s) > 4000:
        raise SQLRejected("Câu truy vấn quá dài")
    # Bỏ chuỗi ký tự trước khi kiểm tra để từ khóa nằm trong chuỗi không gây báo nhầm
    bare = _STRING.sub("''", s)
    if "--" in bare or "/*" in bare or "*/" in bare:
        raise SQLRejected("Câu truy vấn có chú thích (comment), không được phép")
    if ";" in bare:
        raise SQLRejected("Chỉ được chạy đúng một câu lệnh SELECT")
    bare = _QUOTED_ID.sub(lambda m: next(g for g in m.groups() if g is not None), bare)
    if not re.match(r"^\s*(select|with)\b", bare, re.I):
        raise SQLRejected("Chỉ được chạy câu lệnh SELECT")
    m = FORBIDDEN.search(bare)
    if m:
        raise SQLRejected(f"Câu truy vấn chứa từ khóa bị cấm: {m.group(1).upper()}")
    m = SYSTEM_FUNCS.search(bare)
    if m:
        raise SQLRejected("Câu truy vấn gọi hàm hệ thống, không được phép")

    ctes = {n.lower() for n in _CTE_NAME.findall(bare)}
    tables = {t.lower() for t in _FROM_JOIN.findall(bare) if t != "("}
    for group in _FROM_LIST.findall(bare):  # FROM a x, b y
        for part in group.split(","):
            tables.add(part.strip().split()[0].lower())
    if not tables:
        raise SQLRejected("Câu truy vấn không đọc từ view nào")
    bad = sorted(t for t in tables if t not in ALLOWED_VIEWS and t not in ctes)
    if bad:
        raise SQLRejected(f"Chỉ được đọc các view v_ai_*, không được đọc: {', '.join(bad)}")
    # Tên bảng gốc xuất hiện ở bất kỳ đâu (ví dụ trong truy vấn con lồng sâu) cũng bị từ chối
    words = {w.lower() for w in re.findall(r"[A-Za-z_]\w*", bare)}
    leaked = sorted(words & _base_tables())
    if leaked:
        raise SQLRejected(f"Không được truy cập bảng gốc: {', '.join(leaked)}")
    return s


# ---------------------------------------------------------------- Lớp 4, 5: chạy chỉ đọc, LIMIT, timeout
@dataclass
class QueryResult:
    sql: str
    columns: list[str] = field(default_factory=list)
    rows: list[list] = field(default_factory=list)
    truncated: bool = False


def _sqlite_path(db: Session) -> str | None:
    url = db.get_bind().url
    path = url.database
    return path if path and path != ":memory:" else None


@contextmanager
def readonly_connection(db: Session, timeout: float = TIMEOUT_SECONDS):
    """Lớp 4: kết nối SQLite chỉ đọc (mode=ro) + PRAGMA query_only = ON. Lớp 5: dừng câu lệnh sau timeout giây."""
    path = _sqlite_path(db)
    own = path is not None
    if own:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=timeout, check_same_thread=False)
    else:  # CSDL trong bộ nhớ (kiểm thử): dùng chính kết nối, vẫn bật query_only
        conn = db.connection().connection.dbapi_connection
    deadline = time.monotonic() + timeout
    conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 2000)
    conn.execute("PRAGMA query_only = ON")
    try:
        yield conn
    finally:
        conn.set_progress_handler(None, 0)
        if own:
            conn.close()
        else:
            conn.execute("PRAGMA query_only = OFF")


def run_sql(db: Session, sql: str, timeout: float = TIMEOUT_SECONDS) -> QueryResult:
    """Chạy câu SELECT đã qua validate_sql. Ném SQLTimeout khi quá thời gian, sqlite3.Error khi SQL lỗi."""
    safe = validate_sql(sql)  # kiểm tra lại ngay tại chỗ chạy, không tin bên gọi
    ensure_views(db.connection())
    db.commit()  # view mới tạo phải được ghi trước khi mở kết nối chỉ đọc
    wrapped = f"SELECT * FROM (\n{safe}\n) LIMIT {MAX_ROWS + 1}"  # lớp 5: luôn có LIMIT
    with readonly_connection(db, timeout) as conn:
        try:
            cur = conn.execute(wrapped)
            columns = [d[0] for d in cur.description or []]
            rows = [list(r) for r in cur.fetchmany(MAX_ROWS + 1)]
        except sqlite3.OperationalError as e:
            if "interrupted" in str(e).lower():
                raise SQLTimeout(f"Truy vấn chạy quá {int(timeout)} giây") from e
            raise
    return QueryResult(sql=safe, columns=columns, rows=rows[:MAX_ROWS], truncated=len(rows) > MAX_ROWS)
