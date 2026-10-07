"""Công cụ tra cứu cho trợ lý AI đa năng (Gemini function calling).

Thiết kế an toàn, cùng tinh thần với hỏi đáp dữ liệu:
- AI KHÔNG sinh SQL. Nó chỉ được gọi các hàm CHỈ ĐỌC định nghĩa sẵn dưới đây; tham số được kiểm tra,
  giới hạn số dòng trả về.
- Mỗi công cụ gắn nhóm quyền. Nhân viên không được khai báo (và không gọi được) công cụ báo cáo của
  chủ cửa hàng; hóa đơn chỉ thấy hóa đơn mình lập, giống hệt quyền trên giao diện.
- Không trả về SĐT đầy đủ, email, địa chỉ khách hàng; giá vốn chỉ trả cho quản lý.
"""
import json
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.ai.service import fmt_vnd, mask_phone, strip_accents
from app.config import settings
from app.models import (PAID_STATES, Category, Customer, ImportItem, ImportReceipt, Invoice, InvoiceItem, Product,
                        StockMovement, User, now)
from app.routers.invoices import invoice_query
from app.services import reports

logger = logging.getLogger("ai")

PAY_VI = {"cash": "Tiền mặt", "bank_transfer": "Chuyển khoản", "card": "Quẹt thẻ"}
STATUS_VI = {"draft": "nháp", "pending_payment": "chờ thanh toán", "paid": "đã thanh toán",
             "partially_returned": "đã trả một phần", "fully_returned": "đã trả toàn bộ", "cancelled": "đã hủy"}
GROUP_VI = {"regular": "Thường", "vip": "VIP", "wholesale": "Khách sỉ"}
MOVE_VI = {"import": "Nhập hàng", "import_cancel": "Hủy phiếu nhập", "sale": "Bán hàng", "cancel": "Hủy hóa đơn",
           "edit": "Sửa hóa đơn", "return": "Khách trả hàng", "adjust": "Kiểm kho"}
WEEKDAYS_VI = ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ nhật"]
_STOP = {"toi", "can", "mua", "cho", "mot", "cai", "co", "khong", "duoi", "tren", "gia", "khach", "hang",
         "con", "va", "la", "nao", "loai", "muon", "tim", "san", "pham", "the", "nhu", "bao", "nhieu",
         "lam", "sao", "de", "cach", "huong", "dan", "dau", "duoc", "gi", "vay", "minh"}


class ToolError(Exception):
    """Lỗi tham số / không tìm thấy dữ liệu: trả lại cho AI để nó tự sửa hoặc báo người dùng."""


@dataclass
class Tool:
    name: str
    label: str  # tên hiển thị trên giao diện ("Đã tra cứu: ...")
    description: str
    fn: Callable[[Session, User, dict], dict]
    params: dict = field(default_factory=dict)
    required: tuple[str, ...] = ()
    managers_only: bool = False


TOOLS: dict[str, Tool] = {}


def tool(name: str, label: str, description: str, params: dict | None = None,
         required: tuple[str, ...] = (), managers_only: bool = False):
    def deco(fn):
        TOOLS[name] = Tool(name, label, description, fn, params or {}, required, managers_only)
        return fn
    return deco


def is_manager(user: User) -> bool:
    return user.role in ("admin", "owner")


def available(user: User) -> list[Tool]:
    return [t for t in TOOLS.values() if is_manager(user) or not t.managers_only]


def declarations(tools: list[Tool]) -> list[dict]:
    out = []
    for t in tools:
        decl = {"name": t.name, "description": t.description}
        if t.params:
            decl["parameters"] = {"type": "OBJECT", "properties": t.params, "required": list(t.required)}
        out.append(decl)
    return out


def run(db: Session, user: User, name: str, args: dict | None) -> dict:
    """Thực thi một lệnh gọi công cụ của AI. Không bao giờ ném lỗi: lỗi được trả về dạng {"error": ...}."""
    t = TOOLS.get(name)
    if t is None or (t.managers_only and not is_manager(user)):
        return {"error": f"Công cụ '{name}' không tồn tại hoặc vai trò hiện tại không có quyền sử dụng."}
    try:
        result = t.fn(db, user, dict(args or {}))
    except ToolError as e:
        return {"error": str(e)}
    except Exception:
        logger.exception("Lỗi khi chạy công cụ AI %s", name)
        return {"error": "Có lỗi khi tra cứu dữ liệu, hãy thử lại."}
    return json.loads(json.dumps(result, ensure_ascii=False, default=str))  # đảm bảo gửi được dạng JSON


# ---------------------------------------------------------------- đọc tham số
def _str(a: dict, key: str, max_len: int = 100) -> str | None:
    v = a.get(key)
    if v is None:
        return None
    v = " ".join(str(v).split())[:max_len]
    return v or None


def _int(a: dict, key: str, default: int | None, lo: int = 0, hi: int = 10**12) -> int | None:
    v = a.get(key)
    if v is None or v == "":
        return default
    try:
        n = int(float(v))
    except (TypeError, ValueError):
        raise ToolError(f"Tham số {key} phải là số")
    return max(lo, min(hi, n))


def _bool(a: dict, key: str, default: bool) -> bool:
    v = a.get(key)
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "yes")
    return default if v is None else bool(v)


def _enum(a: dict, key: str, choices: tuple[str, ...], default: str) -> str:
    v = _str(a, key)
    if v is None:
        return default
    if v not in choices:
        raise ToolError(f"Tham số {key} phải là một trong: {', '.join(choices)}")
    return v


def _date(a: dict, key: str) -> date | None:
    v = _str(a, key)
    if not v:
        return None
    try:
        return date.fromisoformat(v[:10])
    except ValueError:
        raise ToolError(f"{key} không hợp lệ ('{v}'), dùng định dạng YYYY-MM-DD")


def _period(a: dict) -> tuple[datetime, datetime, dict]:
    """Kỳ dữ liệu từ date_from/date_to. Mặc định: từ đầu tháng đến hôm nay."""
    d_to = _date(a, "date_to") or now().date()
    d_from = _date(a, "date_from") or d_to.replace(day=1)
    start, end = reports.parse_range(d_from, d_to)
    return start, end, {"from": start.date().isoformat(), "to": (end - timedelta(days=1)).date().isoformat(),
                        "days": (end - start).days}


def _paid(start: datetime, end: datetime):
    return Invoice.status.in_(PAID_STATES), Invoice.paid_at >= start, Invoice.paid_at < end


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", strip_accents(text)) if len(w) > 1 and w not in _STOP}


def _stock_state(p: Product) -> str:
    if p.stock <= 0:
        return "hết hàng"
    return "sắp hết" if p.stock <= p.min_stock else "còn hàng"


def _brief(p: Product) -> dict:
    return {"code": p.code, "name": p.name, "category": p.category.name if p.category else None,
            "price": p.sale_price, "stock": p.stock, "stock_state": _stock_state(p),
            "description": (p.description or "")[:160]}


def _resolve_product(db: Session, key: str) -> Product | list[Product]:
    """Tìm sản phẩm theo mã chính xác, hoặc theo tên (không phân biệt dấu). Nhiều kết quả => trả list."""
    p = db.scalar(select(Product).options(joinedload(Product.category))
                  .where(func.upper(Product.code) == key.strip().upper()))
    if p:
        return p
    words = _words(key)
    if not words:
        raise ToolError(f"Không tìm thấy sản phẩm '{key}'")
    scored = []
    for p in db.scalars(select(Product).options(joinedload(Product.category))):
        name = strip_accents(f"{p.code} {p.name}")
        hits = sum(1 for w in words if w in name)
        if hits:
            scored.append((hits, p))
    full = [p for hits, p in scored if hits == len(words)]
    if len(full) == 1:
        return full[0]
    candidates = full or [p for _, p in sorted(scored, key=lambda x: -x[0])[:5]]
    if not candidates:
        raise ToolError(f"Không tìm thấy sản phẩm '{key}'")
    return candidates


DATE_FROM = {"type": "STRING", "description": "Ngày bắt đầu, định dạng YYYY-MM-DD. Bỏ trống = ngày đầu tháng này."}
DATE_TO = {"type": "STRING", "description": "Ngày kết thúc (tính cả ngày này), YYYY-MM-DD. Bỏ trống = hôm nay."}


# ================================================================ Công cụ cho mọi nhân viên
@tool("search_products", "Tìm sản phẩm",
      "Tìm sản phẩm đang kinh doanh theo từ khóa, nhóm hàng, khoảng giá. Dùng để tư vấn khách, kiểm tra giá, "
      "còn hàng hay không. Từ khóa nên ngắn (VD: 'tai nghe', 'sạc', 'loa'); để trống keyword để duyệt theo "
      "nhóm hàng / khoảng giá (hữu ích khi nhu cầu mơ hồ như 'quà tặng').",
      params={
          "keyword": {"type": "STRING", "description": "Từ khóa tên / mô tả / mã sản phẩm"},
          "category": {"type": "STRING", "description": "Tên nhóm hàng, VD: Phụ kiện, Điện thoại, Âm thanh"},
          "min_price": {"type": "INTEGER", "description": "Giá bán tối thiểu (VND)"},
          "max_price": {"type": "INTEGER", "description": "Giá bán tối đa / ngân sách (VND)"},
          "in_stock_only": {"type": "BOOLEAN", "description": "Chỉ lấy hàng còn tồn. Mặc định true"},
          "sort": {"type": "STRING", "enum": ["relevance", "price_asc", "price_desc", "stock_desc"],
                   "description": "Cách sắp xếp. Mặc định relevance"},
          "limit": {"type": "INTEGER", "description": "Số sản phẩm tối đa (1-30), mặc định 10"},
      })
def search_products(db: Session, user: User, a: dict) -> dict:
    keyword, category = _str(a, "keyword"), _str(a, "category")
    min_price, max_price = _int(a, "min_price", None), _int(a, "max_price", None)
    in_stock_only = _bool(a, "in_stock_only", True)
    sort = _enum(a, "sort", ("relevance", "price_asc", "price_desc", "stock_desc"), "relevance")
    limit = _int(a, "limit", 10, 1, 30)
    words = _words(keyword) if keyword else set()
    cat_key = strip_accents(category) if category else None

    rows = []
    for p in db.scalars(select(Product).options(joinedload(Product.category)).where(Product.status == "active")):
        cat = p.category.name if p.category else ""
        if (in_stock_only and p.stock <= 0) or (min_price is not None and p.sale_price < min_price) \
                or (max_price is not None and p.sale_price > max_price) \
                or (cat_key and cat_key not in strip_accents(cat)):
            continue
        score = 0
        if words:
            hay = strip_accents(f"{p.code} {p.name} {cat} {p.description or ''}")
            name = strip_accents(f"{p.code} {p.name}")
            score = sum(2 if w in name else 1 for w in words if w in hay)
            if not score:
                continue
        rows.append((score, p))
    order = {
        "relevance": lambda x: (-x[0], x[1].sale_price),
        "price_asc": lambda x: x[1].sale_price,
        "price_desc": lambda x: -x[1].sale_price,
        "stock_desc": lambda x: -x[1].stock,
    }[sort]
    rows.sort(key=order)
    result = {"total_found": len(rows), "items": [_brief(p) for _, p in rows[:limit]]}
    if not rows:
        result["hint"] = ("Không có sản phẩm khớp. Thử từ khóa khác ngắn hơn, bỏ lọc giá, "
                          "hoặc để trống keyword để xem theo nhóm hàng.")
    return result


@tool("get_product", "Chi tiết sản phẩm",
      "Xem chi tiết một sản phẩm theo mã (VD: PK001) hoặc tên: giá, tồn kho, mức tồn tối thiểu, trạng thái, "
      "số lượng bán 30 ngày qua (quản lý thấy thêm giá vốn và biên lãi).",
      params={"code_or_name": {"type": "STRING", "description": "Mã sản phẩm hoặc tên sản phẩm"}},
      required=("code_or_name",))
def get_product(db: Session, user: User, a: dict) -> dict:
    key = _str(a, "code_or_name")
    if not key:
        raise ToolError("Cần mã hoặc tên sản phẩm")
    found = _resolve_product(db, key)
    if isinstance(found, list):
        return {"note": "Có nhiều sản phẩm khớp, hãy chọn một mã cụ thể.", "matches": [_brief(p) for p in found]}
    p = found
    start = datetime.combine(now().date() - timedelta(days=29), datetime.min.time())
    sold = db.scalar(select(func.coalesce(func.sum(InvoiceItem.quantity), 0)).join(Invoice)
                     .where(InvoiceItem.product_id == p.id, *_paid(start, now() + timedelta(days=1))))
    data = {**_brief(p), "description": (p.description or "")[:500], "min_stock": p.min_stock,
            "status": "đang bán" if p.status == "active" else "ngừng bán", "sold_last_30_days": int(sold)}
    if is_manager(user):
        margin = p.sale_price - p.cost_price
        data.update(cost_price=p.cost_price, margin_per_unit=margin,
                    margin_percent=round(margin / p.sale_price * 100, 1) if p.sale_price else None)
    return data


@tool("list_categories", "Nhóm hàng",
      "Liệt kê các nhóm hàng: số sản phẩm đang bán, số sản phẩm còn hàng, khoảng giá.")
def list_categories(db: Session, user: User, a: dict) -> dict:
    stats: dict[str, dict] = {}
    for c in db.scalars(select(Category).order_by(Category.name)):
        stats[c.name] = {"category": c.name, "description": c.description, "products": 0, "in_stock": 0,
                         "min_price": None, "max_price": None}
    for p in db.scalars(select(Product).options(joinedload(Product.category)).where(Product.status == "active")):
        name = p.category.name if p.category else "Chưa phân nhóm"
        s = stats.setdefault(name, {"category": name, "description": None, "products": 0, "in_stock": 0,
                                    "min_price": None, "max_price": None})
        s["products"] += 1
        s["in_stock"] += p.stock > 0
        s["min_price"] = p.sale_price if s["min_price"] is None else min(s["min_price"], p.sale_price)
        s["max_price"] = p.sale_price if s["max_price"] is None else max(s["max_price"], p.sale_price)
    return {"categories": list(stats.values())}


@tool("find_invoices", "Tra hóa đơn",
      "Tìm hóa đơn theo mã (VD: HD-20261001-0001), tên / mã khách hàng, khoảng ngày, trạng thái, phương thức thanh toán. "
      "Trả về tổng số hóa đơn khớp, tổng tiền đã thanh toán và danh sách chi tiết. "
      "Nhân viên chỉ thấy hóa đơn do chính mình lập.",
      params={
          "keyword": {"type": "STRING", "description": "Mã hóa đơn, tên hoặc mã khách hàng"},
          "date_from": {"type": "STRING", "description": "Từ ngày YYYY-MM-DD (bỏ trống = không giới hạn)"},
          "date_to": {"type": "STRING", "description": "Đến ngày YYYY-MM-DD (bỏ trống = không giới hạn)"},
          "status": {"type": "STRING", "enum": ["paid", "cancelled", "pending_payment", "partially_returned", "fully_returned"],
                     "description": "paid = đã thanh toán, cancelled = đã hủy, pending_payment = chờ chuyển khoản, "
                                    "partially_returned / fully_returned = khách đã trả một phần / toàn bộ"},
          "payment_method": {"type": "STRING", "enum": list(PAY_VI), "description": "Phương thức thanh toán"},
          "order": {"type": "STRING", "enum": ["newest", "largest"], "description": "Mới nhất hoặc giá trị lớn nhất"},
          "limit": {"type": "INTEGER", "description": "Số hóa đơn trả về (1-10), mặc định 5"},
      })
def find_invoices(db: Session, user: User, a: dict) -> dict:
    status = _enum(a, "status", ("paid", "cancelled", "pending_payment", "partially_returned", "fully_returned"), "") or None
    method = _enum(a, "payment_method", tuple(PAY_VI), "") or None
    order = _enum(a, "order", ("newest", "largest"), "newest")
    limit = _int(a, "limit", 5, 1, 10)
    d_from, d_to = _date(a, "date_from"), _date(a, "date_to")
    stmt = invoice_query(user, _str(a, "keyword"), status, d_from and d_from.isoformat(),
                         d_to and d_to.isoformat(), method, None)
    count = db.scalar(select(func.count()).select_from(stmt.subquery()))
    sum_paid = db.scalar(select(func.coalesce(func.sum(Invoice.total), 0)).where(
        Invoice.id.in_(stmt.with_only_columns(Invoice.id).where(Invoice.status.in_(PAID_STATES)))))
    sort = (Invoice.total.desc(),) if order == "largest" else (Invoice.created_at.desc(), Invoice.id.desc())
    rows = db.scalars(stmt.options(joinedload(Invoice.customer), joinedload(Invoice.user),
                                   selectinload(Invoice.items).joinedload(InvoiceItem.product))
                      .order_by(*sort).limit(limit)).unique().all()
    return {
        "matched_count": count, "paid_total": int(sum_paid),
        "scope": "chỉ hóa đơn do bạn lập" if user.role == "staff" else "toàn cửa hàng",
        "invoices": [{
            "code": inv.code, "time": inv.created_at.strftime("%Y-%m-%d %H:%M"),
            "customer": inv.customer.name if inv.customer else "Khách lẻ",
            "customer_code": inv.customer.code if inv.customer else None,
            "staff": inv.user.full_name, "subtotal": inv.subtotal, "discount": inv.discount, "total": inv.total,
            "payment_method": PAY_VI.get(inv.payment_method, inv.payment_method),
            "status": STATUS_VI.get(inv.status, inv.status),
            "cancel_reason": inv.cancel_reason,
            "items": [f"{it.product.name} ({it.product.code}) x{it.quantity} = {fmt_vnd(it.line_total)}" for it in inv.items],
        } for inv in rows],
    }


@tool("find_customers", "Tra khách hàng",
      "Tìm khách hàng theo tên, mã (VD: KH0001) hoặc số điện thoại; trả về nhóm khách, số hóa đơn, "
      "tổng chi tiêu, lần mua gần nhất. SĐT được che bớt để bảo mật.",
      params={
          "keyword": {"type": "STRING", "description": "Tên, mã khách hoặc số điện thoại"},
          "group": {"type": "STRING", "enum": list(GROUP_VI), "description": "regular = thường, vip, wholesale = khách sỉ"},
          "limit": {"type": "INTEGER", "description": "Số khách trả về (1-10), mặc định 5"},
      })
def find_customers(db: Session, user: User, a: dict) -> dict:
    keyword = _str(a, "keyword")
    group = _enum(a, "group", tuple(GROUP_VI), "") or None
    limit = _int(a, "limit", 5, 1, 10)
    stmt = select(Customer)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(Customer.name.ilike(like) | Customer.code.ilike(like) | Customer.phone.ilike(like))
    if group:
        stmt = stmt.where(Customer.group == group)
    count = db.scalar(select(func.count()).select_from(stmt.subquery()))
    customers = db.scalars(stmt.order_by(Customer.id.desc()).limit(limit)).all()
    stats = {cid: (n, spent, last) for cid, n, spent, last in db.execute(
        select(Invoice.customer_id, func.count(Invoice.id), func.sum(Invoice.total), func.max(Invoice.created_at))
        .where(Invoice.status.in_(PAID_STATES), Invoice.customer_id.in_([c.id for c in customers]))
        .group_by(Invoice.customer_id))}
    out = []
    for c in customers:
        n, spent, last = stats.get(c.id, (0, 0, None))
        out.append({"code": c.code, "name": c.name, "group": GROUP_VI.get(c.group, c.group),
                    "phone_masked": mask_phone(c.phone), "invoice_count": n, "total_spent": int(spent or 0),
                    "last_purchase": last.strftime("%Y-%m-%d") if last else None, "note": c.note})
    return {"matched_count": count, "customers": out}


def _guide_sections() -> list[tuple[str, str]]:
    raw = (settings.PROMPTS_DIR / "app_guide.md").read_text(encoding="utf-8")
    raw = re.sub(r"<!--.*?-->", "", raw, flags=re.S)
    return [(s.split("\n", 1)[0].strip(), s.strip()) for s in re.split(r"^## ", raw, flags=re.M)[1:]]


@tool("app_guide", "Hướng dẫn sử dụng",
      "Tra cứu hướng dẫn sử dụng phần mềm TechStoreAI: bán hàng, thanh toán, quét QR, hủy/sửa hóa đơn, nhập hàng, "
      "kiểm kho, sản phẩm, khách hàng, báo cáo, xuất file, phân quyền, các chức năng AI.",
      params={"topic": {"type": "STRING", "description": "Chủ đề cần hướng dẫn, VD: 'hủy hóa đơn', 'nhập hàng'"}},
      required=("topic",))
def app_guide(db: Session, user: User, a: dict) -> dict:
    sections = _guide_sections()
    words = _words(_str(a, "topic", 200) or "")
    scored = []
    for title, text in sections:
        t, body = strip_accents(title), strip_accents(text)
        score = sum(3 if w in t else 1 for w in words if w in body)
        if score:
            scored.append((score, text))
    scored.sort(key=lambda x: -x[0])
    if not scored:
        return {"note": "Không có mục khớp chủ đề.", "topics": [t for t, _ in sections]}
    return {"sections": [text for _, text in scored[:3]]}


# ================================================================ Công cụ chỉ dành cho quản lý
@tool("sales_summary", "Doanh thu tổng hợp",
      "Tổng hợp kinh doanh trong một kỳ: doanh thu, số hóa đơn, giá trị trung bình/hóa đơn, giảm giá, giá vốn, "
      "lãi gộp, so sánh với kỳ liền trước cùng độ dài, hóa đơn bị hủy, doanh thu theo phương thức thanh toán.",
      params={"date_from": DATE_FROM, "date_to": DATE_TO}, managers_only=True)
def sales_summary(db: Session, user: User, a: dict) -> dict:
    start, end, period = _period(a)
    cur = reports.revenue_total(db, start, end)
    prev_start = start - (end - start)
    prev = reports.revenue_total(db, prev_start, start)
    cancelled = db.execute(select(func.count(Invoice.id), func.coalesce(func.sum(Invoice.total), 0)).where(
        Invoice.status == "cancelled", Invoice.created_at >= start, Invoice.created_at < end)).one()
    by_method = db.execute(select(Invoice.payment_method, func.count(Invoice.id), func.sum(Invoice.total))
                           .where(*_paid(start, end)).group_by(Invoice.payment_method)).all()
    return {
        "period": period,
        "summary": {**cur, "average_invoice": cur["revenue"] // cur["invoice_count"] if cur["invoice_count"] else 0,
                    "gross_margin_percent": round(cur["gross_profit"] / cur["revenue"] * 100, 1) if cur["revenue"] else None},
        "previous_period": {"from": prev_start.date().isoformat(), "to": (start - timedelta(days=1)).date().isoformat(), **prev},
        "revenue_growth_percent": round((cur["revenue"] - prev["revenue"]) / prev["revenue"] * 100, 1) if prev["revenue"] else None,
        "cancelled": {"count": cancelled[0], "value": int(cancelled[1])},
        "by_payment_method": [{"method": PAY_VI.get(m, m), "invoice_count": n, "revenue": int(t)}
                              for m, n, t in sorted(by_method, key=lambda r: -r[2])],
    }


@tool("revenue_breakdown", "Phân tích doanh thu",
      "Chia doanh thu theo chiều: day (từng ngày, tối đa 93 ngày), month (từng tháng), category (nhóm hàng), "
      "payment_method, staff (nhân viên bán), hour (khung giờ trong ngày), weekday (thứ trong tuần). "
      "Dùng cho câu hỏi về xu hướng, so sánh, giờ cao điểm, nhân viên bán tốt...",
      params={
          "group_by": {"type": "STRING", "enum": ["day", "month", "category", "payment_method", "staff", "hour", "weekday"],
                       "description": "Chiều phân tích"},
          "date_from": DATE_FROM, "date_to": DATE_TO,
      }, required=("group_by",), managers_only=True)
def revenue_breakdown(db: Session, user: User, a: dict) -> dict:
    group_by = _enum(a, "group_by", ("day", "month", "category", "payment_method", "staff", "hour", "weekday"), "day")
    start, end, period = _period(a)
    if group_by == "category":
        return {"period": period, "group_by": group_by, "rows": reports.revenue_by_category(db, start, end)}
    if group_by == "day":
        if period["days"] > 93:
            raise ToolError("Khoảng thời gian quá dài để xem theo ngày (tối đa 93 ngày), hãy dùng group_by='month'.")
        return {"period": period, "group_by": group_by, "rows": reports.revenue_by_day(db, start, end)}

    key_fn, sort_fn = {
        "month": (lambda r: r.created_at.strftime("%Y-%m"), lambda k: k),
        "hour": (lambda r: r.created_at.hour, lambda k: k),
        "weekday": (lambda r: r.created_at.weekday(), lambda k: k),
        "payment_method": (lambda r: PAY_VI.get(r.payment_method, r.payment_method), None),
        "staff": (lambda r: r.full_name, None),
    }[group_by]
    buckets: dict = defaultdict(lambda: {"revenue": 0, "invoice_count": 0})
    for r in db.execute(select(Invoice.created_at, Invoice.total, Invoice.payment_method, User.full_name)
                        .join(User, Invoice.user_id == User.id).where(*_paid(start, end))):
        b = buckets[key_fn(r)]
        b["revenue"] += r.total
        b["invoice_count"] += 1
    keys = sorted(buckets, key=sort_fn) if sort_fn else sorted(buckets, key=lambda k: -buckets[k]["revenue"])
    label = {"hour": lambda k: f"{k:02d}h-{k + 1:02d}h", "weekday": lambda k: WEEKDAYS_VI[k]}.get(group_by, str)
    return {"period": period, "group_by": group_by, "rows": [{"key": label(k), **buckets[k]} for k in keys]}


@tool("product_sales_ranking", "Xếp hạng bán hàng",
      "Xếp hạng sản phẩm theo số lượng bán trong kỳ: best = bán chạy nhất, slow = bán chậm nhất "
      "(đang kinh doanh, còn tồn nhưng bán ít hoặc không bán được).",
      params={
          "order": {"type": "STRING", "enum": ["best", "slow"], "description": "best = bán chạy, slow = bán chậm"},
          "date_from": DATE_FROM, "date_to": DATE_TO,
          "limit": {"type": "INTEGER", "description": "Số sản phẩm (1-20), mặc định 10"},
      }, required=("order",), managers_only=True)
def product_sales_ranking(db: Session, user: User, a: dict) -> dict:
    order = _enum(a, "order", ("best", "slow"), "best")
    limit = _int(a, "limit", 10, 1, 20)
    start, end, period = _period(a)
    fn = reports.top_products if order == "best" else reports.slow_products
    return {"period": period, "order": order, "products": fn(db, start, end, limit)}


@tool("inventory_report", "Báo cáo tồn kho",
      "Tình hình tồn kho hiện tại: tổng số lượng, giá trị tồn theo giá vốn và giá bán, theo nhóm hàng; "
      "kèm danh sách low (sắp hết, tồn <= mức tối thiểu, cần nhập thêm), out (hết hàng) hoặc all (tất cả, theo giá trị tồn).",
      params={
          "filter": {"type": "STRING", "enum": ["low", "out", "all"], "description": "Danh sách kèm theo, mặc định low"},
          "category": {"type": "STRING", "description": "Lọc theo tên nhóm hàng"},
      }, managers_only=True)
def inventory_report(db: Session, user: User, a: dict) -> dict:
    flt = _enum(a, "filter", ("low", "out", "all"), "low")
    cat_key = strip_accents(_str(a, "category") or "")
    products = [p for p in db.scalars(select(Product).options(joinedload(Product.category))
                                      .where(Product.status == "active"))
                if not cat_key or cat_key in strip_accents(p.category.name if p.category else "")]
    by_cat: dict = defaultdict(lambda: {"units": 0, "value_at_cost": 0})
    for p in products:
        c = by_cat[p.category.name if p.category else "Chưa phân nhóm"]
        c["units"] += p.stock
        c["value_at_cost"] += p.stock * p.cost_price
    pick = {
        "low": lambda p: p.stock <= p.min_stock,
        "out": lambda p: p.stock <= 0,
        "all": lambda p: True,
    }[flt]
    items = sorted((p for p in products if pick(p)),
                   key=(lambda p: -p.stock * p.cost_price) if flt == "all" else (lambda p: p.stock))
    return {
        "summary": {"active_products": len(products), "total_units": sum(p.stock for p in products),
                    "value_at_cost": sum(p.stock * p.cost_price for p in products),
                    "value_at_sale_price": sum(p.stock * p.sale_price for p in products),
                    "out_of_stock": sum(p.stock <= 0 for p in products),
                    "low_stock": sum(p.stock <= p.min_stock for p in products)},
        "by_category": [{"category": k, **v} for k, v in sorted(by_cat.items(), key=lambda x: -x[1]["value_at_cost"])],
        "filter": flt,
        "items": [{"code": p.code, "name": p.name, "stock": p.stock, "min_stock": p.min_stock,
                   "cost_price": p.cost_price, "value_at_cost": p.stock * p.cost_price} for p in items[:30]],
    }


@tool("top_customers", "Khách mua nhiều",
      "Xếp hạng khách hàng theo tổng chi tiêu trong kỳ (số hóa đơn, tổng tiền, lần mua gần nhất) "
      "và doanh thu từ khách lẻ không lưu thông tin. SĐT được che bớt.",
      params={"date_from": DATE_FROM, "date_to": DATE_TO,
              "limit": {"type": "INTEGER", "description": "Số khách (1-20), mặc định 5"}},
      managers_only=True)
def top_customers(db: Session, user: User, a: dict) -> dict:
    limit = _int(a, "limit", 5, 1, 20)
    start, end, period = _period(a)
    spent = func.sum(Invoice.total)
    rows = db.execute(select(Customer, func.count(Invoice.id), spent, func.max(Invoice.created_at))
                      .join(Invoice, Invoice.customer_id == Customer.id).where(*_paid(start, end))
                      .group_by(Customer.id).order_by(spent.desc()).limit(limit)).all()
    walk_in = db.execute(select(func.count(Invoice.id), func.coalesce(func.sum(Invoice.total), 0))
                         .where(Invoice.customer_id.is_(None), *_paid(start, end))).one()
    return {
        "period": period,
        "customers": [{"code": c.code, "name": c.name, "group": GROUP_VI.get(c.group, c.group),
                       "phone_masked": mask_phone(c.phone), "invoice_count": n, "total_spent": int(s),
                       "last_purchase": last.strftime("%Y-%m-%d")} for c, n, s, last in rows],
        "walk_in_customers": {"invoice_count": walk_in[0], "revenue": int(walk_in[1])},
    }


@tool("stock_history", "Lịch sử kho",
      "Lịch sử nhập - xuất - tồn gần nhất của một sản phẩm (nhập hàng, bán, hủy/sửa hóa đơn, kiểm kho).",
      params={"product": {"type": "STRING", "description": "Mã hoặc tên sản phẩm"},
              "limit": {"type": "INTEGER", "description": "Số dòng (1-30), mặc định 10"}},
      required=("product",), managers_only=True)
def stock_history(db: Session, user: User, a: dict) -> dict:
    found = _resolve_product(db, _str(a, "product") or "")
    if isinstance(found, list):
        return {"note": "Có nhiều sản phẩm khớp, hãy chọn một mã cụ thể.", "matches": [_brief(p) for p in found]}
    moves = db.scalars(select(StockMovement).where(StockMovement.product_id == found.id)
                       .order_by(StockMovement.created_at.desc(), StockMovement.id.desc())
                       .limit(_int(a, "limit", 10, 1, 30))).all()
    return {"product": _brief(found), "movements": [
        {"time": m.created_at.strftime("%Y-%m-%d %H:%M"), "type": MOVE_VI.get(m.type, m.type), "change": m.change,
         "stock_after": m.stock_after, "ref": m.ref_code, "note": m.note} for m in moves]}


@tool("import_history", "Lịch sử nhập hàng",
      "Các phiếu nhập hàng trong kỳ: nhà cung cấp, tổng tiền, mặt hàng và giá nhập; có thể lọc theo sản phẩm.",
      params={"date_from": DATE_FROM, "date_to": DATE_TO,
              "product": {"type": "STRING", "description": "Mã hoặc tên sản phẩm (tùy chọn)"},
              "limit": {"type": "INTEGER", "description": "Số phiếu (1-20), mặc định 10"}},
      managers_only=True)
def import_history(db: Session, user: User, a: dict) -> dict:
    start, end, period = _period(a)
    stmt = select(ImportReceipt).where(ImportReceipt.created_at >= start, ImportReceipt.created_at < end)
    product = _str(a, "product")
    if product:
        found = _resolve_product(db, product)
        ids = [p.id for p in found] if isinstance(found, list) else [found.id]
        stmt = stmt.where(ImportReceipt.items.any(ImportItem.product_id.in_(ids)))
    sub = stmt.subquery()
    count, total = db.execute(select(func.count(), func.coalesce(func.sum(sub.c.total), 0)).select_from(sub)).one()
    receipts = db.scalars(stmt.options(selectinload(ImportReceipt.items).joinedload(ImportItem.product))
                          .order_by(ImportReceipt.created_at.desc()).limit(_int(a, "limit", 10, 1, 20))).all()
    return {"period": period, "receipt_count": count, "total_value": int(total), "receipts": [
        {"code": r.code, "time": r.created_at.strftime("%Y-%m-%d %H:%M"), "supplier": r.supplier, "total": r.total,
         "items": [f"{it.product.name} ({it.product.code}) x{it.quantity}, giá nhập {fmt_vnd(it.unit_cost)}" for it in r.items]}
        for r in receipts]}
