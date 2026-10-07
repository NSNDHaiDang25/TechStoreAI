"""3 chức năng AI: chatbot tư vấn sản phẩm, sinh báo cáo doanh thu, hỏi đáp dữ liệu bán hàng.

Mỗi chức năng đều có chế độ dự phòng (rule-based) khi chưa cấu hình API key hoặc khi AI lỗi,
để hệ thống vẫn hoạt động và demo được.
"""
import json
import re
import sqlite3
import unicodedata
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.ai import text_to_sql as tts
from app.ai.client import AIError, AIResult, GeminiClient
from app.ai.prompts import render_prompt
from app.ai.sanitizer import scrub
from app.models import Product, now
from app.services import reports

ADVISOR_VERSIONS = {
    # in_stock_only: chỉ gửi sản phẩm còn hàng; json: yêu cầu đầu ra JSON
    "v1": {"in_stock_only": False, "json": False},
    "v2": {"in_stock_only": False, "json": False},
    "v3": {"in_stock_only": True, "json": True},
}
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


# ---------------------------------------------------------------- tiện ích
def strip_accents(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower()).replace("đ", "d")
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def clean_input(text: str, max_len: int = 1000) -> str:
    """Loại ký tự điều khiển, cắt độ dài: giảm rủi ro chèn dữ liệu rác vào prompt."""
    return _CONTROL.sub("", text).strip()[:max_len]


def mask_phone(phone: str | None) -> str | None:
    """0901234567 -> 090****567. Dùng khi buộc phải đưa thông tin khách vào prompt."""
    if not phone:
        return phone
    digits = re.sub(r"\D", "", phone)
    if len(digits) < 7:
        return "*" * len(digits)
    return digits[:3] + "*" * (len(digits) - 6) + digits[-3:]


def fmt_vnd(value: int) -> str:
    return f"{value:,.0f}".replace(",", ".") + " ₫"


def parse_budget(text: str) -> int | None:
    """Tìm ngân sách tối đa trong câu: 'dưới 500000', '500k', '1,5 triệu', '2tr'."""
    t = strip_accents(text).replace(",", ".")
    m = re.search(r"(\d+(?:\.\d+)?)\s*(trieu|tr)\b", t)
    if m:
        return int(float(m.group(1)) * 1_000_000)
    m = re.search(r"(\d+(?:\.\d+)?)\s*(k|nghin|ngan)\b", t)
    if m:
        return int(float(m.group(1)) * 1_000)
    m = re.search(r"(\d{1,3}(?:\.\d{3})+|\d{5,})", t)
    if m:
        return int(m.group(1).replace(".", ""))
    return None


def extract_json(text: str) -> dict:
    """Lấy object JSON từ phản hồi AI, chấp nhận trường hợp bị bọc trong ```json ... ```."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise AIError("AI không trả về JSON", "bad_response")
        try:
            data = json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            raise AIError("JSON từ AI bị hỏng", "bad_response")
    if not isinstance(data, dict):
        raise AIError("JSON từ AI không phải object", "bad_response")
    return data


def product_table(products: list[Product]) -> str:
    lines = []
    for p in products:
        desc = (p.description or "").replace("\n", " ").replace("|", "/").replace("<<<", "").replace(">>>", "")[:200]
        cat = p.category.name if p.category else "-"
        lines.append(f"{p.code} | {p.name} | {cat} | {p.sale_price} | {p.stock} | {desc}")
    return "\n".join(lines) if lines else "(không có sản phẩm nào)"


def _product_dict(p: Product, reason: str = "") -> dict:
    return {"code": p.code, "name": p.name, "price": p.sale_price, "stock": p.stock, "image_url": p.image_url,
            "category": p.category.name if p.category else None, "reason": reason}


# ---------------------------------------------------------------- 1. Chatbot tư vấn
def _active_products(db: Session) -> list[Product]:
    return list(db.scalars(
        select(Product).options(joinedload(Product.category))
        .where(Product.status == "active").order_by(Product.code)
    ))


# Từ đồng nghĩa -> tên nhóm hàng (bỏ dấu) để nhận ra nhóm hàng trong câu hỏi (FR-AIA-02)
_CATEGORY_SYNONYMS = {
    "laptop": ("laptop", "may tinh xach tay", "notebook", "macbook"),
    "may tinh bang": ("may tinh bang", "tablet", "ipad"),
    "dien thoai": ("dien thoai", "smartphone", "iphone", "dt "),
    "lot chuot": ("lot chuot", "mouse pad", "mousepad", "ban di chuot"),
    "chuot": ("chuot", "mouse"),
    "ban phim": ("ban phim", "keyboard", "phim co"),
    "sac": ("sac", "cu sac", "charger", "adapter"),
    "tai nghe": ("tai nghe", "headphone", "earbud", "earphone", "airpods"),
}


def price_range(text: str) -> tuple[int | None, int | None]:
    """Khoảng giá trong câu hỏi: 'dưới 500000' -> (None, 500000); 'trên 10 triệu' -> (10000000, None);
    'từ 5 đến 10 triệu' -> (5000000, 10000000). Không nêu từ chỉ hướng thì coi là giá trần."""
    t = strip_accents(text).replace(",", ".")
    unit_value = {"trieu": 1_000_000, "tr": 1_000_000, "k": 1_000, "nghin": 1_000, "ngan": 1_000}
    rng = re.search(r"(?:tu|khoang)\s*(\d+(?:\.\d+)?)\s*(trieu|tr|k|nghin|ngan)?\s*(?:den|toi|-)\s*"
                    r"(\d+(?:\.\d+)?)\s*(trieu|tr|k|nghin|ngan)\b", t)
    if rng:  # "từ 5 đến 10 triệu": số đầu dùng đơn vị của số sau
        u1, u2 = unit_value[rng.group(2) or rng.group(4)], unit_value[rng.group(4)]
        return int(float(rng.group(1)) * u1), int(float(rng.group(3)) * u2)
    amounts = []
    for m in re.finditer(r"(\d+(?:\.\d+)*)\s*(trieu|tr|k|nghin|ngan)?\b", t):
        raw, unit = m.group(1), m.group(2)
        if unit in ("trieu", "tr"):
            value = int(float(raw) * 1_000_000) if raw.count(".") <= 1 else None
        elif unit in ("k", "nghin", "ngan"):
            value = int(float(raw) * 1_000) if raw.count(".") <= 1 else None
        else:
            digits = raw.replace(".", "")
            value = int(digits) if len(digits) >= 5 else None  # bỏ số nhỏ như "20W", "15 inch"
        if value:
            amounts.append((m.start(), value))
    if not amounts:
        return None, None
    if len(amounts) >= 2 and re.search(r"\b(tu|khoang)\b", t) and re.search(r"\b(den|toi)\b|-", t):
        lo, hi = sorted(v for _, v in amounts[:2])
        return lo, hi
    pos, value = amounts[0]
    before = t[max(0, pos - 15):pos]
    if re.search(r"(tren|hon|it nhat|toi thieu|tu)\s*$", before) or re.search(r"tro len", t[pos:pos + 30]):
        return value, None
    return None, value


def narrow_products(products: list[Product], message: str) -> list[Product]:
    """FR-AIA-02: thu hẹp danh sách gửi AI theo nhóm hàng và khoảng giá nhận ra trong câu hỏi.
    Không nhận ra nhóm hàng thì giữ mọi nhóm; khoảng giá luôn được áp dụng khi nhận ra."""
    q = f" {strip_accents(message)} "
    names = {strip_accents(p.category.name): p.category.name for p in products if p.category}
    wanted = set()
    for key, words in _CATEGORY_SYNONYMS.items():
        if key in names and any(re.search(rf"(?<![a-z]){re.escape(w.strip())}(?![a-z])", q) for w in words):
            wanted.add(key)
    for key in names:  # nhóm hàng khác do chủ cửa hàng tự đặt tên
        if key not in _CATEGORY_SYNONYMS and re.search(rf"(?<![a-z]){re.escape(key)}(?![a-z])", q):
            wanted.add(key)
    if "lot chuot" in wanted and not re.search(r"(?<!lot )chuot", q):
        wanted.discard("chuot")  # "lót chuột" không có nghĩa là khách cần chuột
    lo, hi = price_range(message)
    out = []
    for p in products:
        if wanted and (not p.category or strip_accents(p.category.name) not in wanted):
            continue
        if (hi is not None and p.sale_price > hi) or (lo is not None and p.sale_price < lo):
            continue
        out.append(p)
    return out


def _fallback_advise(products: list[Product], message: str) -> dict:
    """Tư vấn dự phòng: chấm điểm theo từ khóa trùng khớp + lọc ngân sách + chỉ hàng còn."""
    stop = {"toi", "can", "mua", "cho", "mot", "cai", "co", "khong", "duoi", "tren", "gia",
            "khach", "hang", "con", "va", "la", "nao", "loai", "muon", "tim", "san", "pham"}
    text = strip_accents(message)
    # Bỏ cụm ngân sách ("20 triệu", "500k", "1.500.000") khỏi từ khóa: "20" không được khớp "Sạc 20W"
    text = re.sub(r"\d+(?:[.,]\d+)*\s*(?:trieu|tr|k|nghin|ngan|dong|d|vnd)?\b", " ", text)
    stop |= {"trieu", "tr", "nghin", "ngan", "dong", "vnd", "tam", "khoang", "re", "dat"}
    words = {w for w in re.findall(r"[a-z0-9]+", text) if len(w) > 1 and w not in stop}
    budget = parse_budget(message)
    tokens = lambda t: set(re.findall(r"[a-z0-9]+", strip_accents(t or "")))  # noqa: E731
    scored = []
    for p in products:
        if p.stock <= 0 or (budget and p.sale_price > budget):
            continue
        cat, name, desc = tokens(p.category.name if p.category else ""), tokens(f"{p.name} {p.brand or ''}"), tokens(p.description)
        # Khớp nguyên từ (không khớp chuỗi con); trùng nhóm hàng nặng nhất, rồi tên / hãng, rồi mô tả
        score = sum(3 if w in cat else 2 if w in name else 1 if w in desc else 0 for w in words)
        if score:
            # Cùng điểm: ưu tiên sản phẩm giá gần ngân sách (khách đã nêu mức chi), không có ngân sách thì rẻ trước
            scored.append((score, p.sale_price if budget else -p.sale_price, p))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    picks = [s[2] for s in scored[:3]]
    if not picks:
        answer = "Hiện chưa tìm thấy sản phẩm còn hàng phù hợp với nhu cầu này. Bạn có thể mô tả rõ hơn loại sản phẩm hoặc ngân sách không?"
    else:
        answer = "Dựa trên nhu cầu của bạn, mình gợi ý các sản phẩm đang còn hàng sau:"
    return {
        "answer": answer,
        "suggestions": [_product_dict(p, f"Khớp nhu cầu, giá {fmt_vnd(p.sale_price)}, còn {p.stock} sản phẩm") for p in picks],
    }


HISTORY_TURNS = 5  # FR-AIA-08: giữ tối đa 5 lượt hỏi - đáp gần nhất làm ngữ cảnh


def _format_history(history: list[dict]) -> str:
    lines = []
    for turn in history[-HISTORY_TURNS * 2:]:
        role = "Khách" if turn.get("role") == "user" else "Trợ lý"
        lines.append(f"{role}: {scrub(clean_input(str(turn.get('content', '')), 300))}")
    return "\n".join(lines) or "(chưa có)"


FORMAT_REMINDER = ("\n\nLƯU Ý: phản hồi trước của bạn sai định dạng. Chỉ trả về đúng một đối tượng JSON hợp lệ "
                   "theo mẫu đã nêu, không kèm văn bản nào khác.")


def advise(db: Session, client: GeminiClient, message: str, history: list[dict] | None = None,
           version: str = "v3") -> dict:
    message = clean_input(message)
    cfg = ADVISOR_VERSIONS.get(version, ADVISOR_VERSIONS["v3"])
    products = _active_products(db)
    by_code = {p.code.upper(): p for p in products}
    sent = [p for p in products if p.stock > 0] if cfg["in_stock_only"] else products
    if cfg["in_stock_only"]:
        # Phiên bản đang dùng: thu hẹp theo nhóm hàng, khoảng giá trước khi gửi (FR-AIA-02, BR-41).
        # v1, v2 giữ nguyên toàn bộ danh sách để thí nghiệm so sánh prompt (SRS 6.7) vẫn đúng thiết kế.
        sent = narrow_products(sent, message)

    if not client.enabled:
        return {**_fallback_advise(products, message), "source": "fallback", "version": version,
                "warning": "Chưa cấu hình GEMINI_API_KEY - đang dùng tư vấn dự phòng theo từ khóa."}

    system, user = render_prompt(
        f"product_advisor_{version}", message=scrub(message), product_table=product_table(sent),
        history=_format_history(history or []),
    )
    try:
        result = client.generate(system, user, json_mode=cfg["json"], temperature=0.2,
                                 feature=f"advisor_{version}")
    except AIError as e:
        return {**_fallback_advise(products, message), "source": "fallback", "version": version,
                "warning": f"{e} - chuyển sang tư vấn dự phòng."}
    retries, latency, bad_format = result.retries, result.latency_ms, False

    # Chuẩn hóa đầu ra về (answer, [(code, reason)])
    raw_suggestions: list[tuple[str, str]] = []
    if cfg["json"]:
        data = None
        for attempt in range(2):  # FR-AIG-05: JSON hỏng thì thử lại một lần, nhắc lại định dạng
            try:
                data = extract_json(result.text)
                break
            except AIError:
                if attempt == 1:
                    break
                try:
                    result = client.generate(system, user + FORMAT_REMINDER, json_mode=True, temperature=0.0,
                                             feature=f"advisor_{version}")
                except AIError:
                    break
                retries += 1 + result.retries
                latency += result.latency_ms
        if data is not None:
            answer = str(data.get("answer", "")).strip()
            for s in data.get("suggestions") or []:
                if isinstance(s, dict) and s.get("code"):
                    raw_suggestions.append((str(s["code"]).upper().strip(), str(s.get("reason", ""))))
        else:
            bad_format = True
            answer = result.text  # vẫn sai định dạng: hiển thị văn bản thô, tự dò mã sản phẩm
            raw_suggestions = _codes_in_text(result.text, by_code)
    else:
        answer = result.text
        raw_suggestions = _codes_in_text(result.text, by_code)

    # Hậu kiểm: chỉ giữ sản phẩm tồn tại, đang bán, còn hàng
    suggestions, removed = [], []
    for code, reason in raw_suggestions[:3]:
        p = by_code.get(code)
        if p is None or p.stock <= 0:
            removed.append(code)
        else:
            suggestions.append(_product_dict(p, reason))

    warning = None
    if removed:
        warning = f"Đã loại bỏ gợi ý không hợp lệ hoặc hết hàng: {', '.join(removed)}"
    if bad_format:
        warning = "AI trả lời sai định dạng hai lần, đang hiển thị nội dung thô" + (f". {warning}" if warning else "")
    out = {"answer": answer or "Xin lỗi, mình chưa có câu trả lời phù hợp.", "suggestions": suggestions,
           "removed": removed, "source": "ai", "version": version, "warning": warning,
           "latency_ms": latency, "model": result.model, "retry_count": retries}
    if bad_format:
        out["status"] = "invalid_format"
    return out


# ---------------------------------------------------------------- 1b. Gợi ý phụ kiện theo giỏ hàng (FR-AIA-07)
# Thiết bị chính -> nhóm phụ kiện dùng kèm (tên nhóm đã bỏ dấu). Dùng cho chế độ dự phòng và để lọc ứng viên.
ACCESSORY_MAP = {
    "laptop": ("chuot", "lot chuot", "ban phim", "tai nghe", "sac"),
    "may tinh bang": ("sac", "tai nghe", "ban phim"),
    "dien thoai": ("sac", "tai nghe"),
    "chuot": ("lot chuot",),
    "ban phim": ("chuot", "lot chuot"),
}
MAIN_DEVICES = ("laptop", "may tinh bang", "dien thoai")


def _cat_key(p: Product) -> str:
    return strip_accents(p.category.name).strip() if p.category else ""


def cross_sell_candidates(db: Session, cart: list[Product]) -> list[Product]:
    """Ứng viên gợi ý: đang bán, còn hàng, chưa có trong giỏ, không phải thiết bị chính cùng loại với hàng trong giỏ."""
    in_cart = {p.id for p in cart}
    cart_cats = {_cat_key(p) for p in cart}
    wanted = {acc for c in cart_cats for acc in ACCESSORY_MAP.get(c, ())}
    out = []
    for p in _active_products(db):
        key = _cat_key(p)
        if p.id in in_cart or p.stock <= 0 or (key in MAIN_DEVICES and key in cart_cats):
            continue
        if wanted and key not in wanted:
            continue
        out.append(p)
    return out


def _fallback_cross_sell(cart: list[Product], candidates: list[Product]) -> dict:
    """Dự phòng: mỗi nhóm phụ kiện phù hợp lấy một sản phẩm giá thấp nhất, tối đa 3 gợi ý."""
    order = [acc for p in cart for acc in ACCESSORY_MAP.get(_cat_key(p), ())]
    picks, seen = [], set()
    for acc in order:
        if acc in seen:
            continue
        seen.add(acc)
        group = sorted((p for p in candidates if _cat_key(p) == acc), key=lambda p: p.sale_price)
        if group:
            picks.append(group[0])
        if len(picks) == 3:
            break
    if not picks:
        return {"answer": "Chưa có phụ kiện còn hàng phù hợp với giỏ hiện tại.", "suggestions": []}
    names = ", ".join(p.name for p in cart[:2])
    return {"answer": "Phụ kiện thường mua kèm, đang còn hàng:",
            "suggestions": [_product_dict(p, f"Thường dùng kèm {names}") for p in picks]}


def cross_sell(db: Session, client: GeminiClient, product_ids: list[int]) -> dict:
    """FR-AIA-07: gợi ý phụ kiện đi kèm dựa trên giỏ hàng hiện tại ở màn hình bán hàng."""
    cart = list(db.scalars(select(Product).options(joinedload(Product.category)).where(Product.id.in_(product_ids))))
    question = "Gợi ý phụ kiện cho giỏ: " + ", ".join(p.code for p in cart)
    if not cart:
        return {"answer": "Giỏ hàng đang trống.", "suggestions": [], "source": "fallback", "question": question}
    candidates = cross_sell_candidates(db, cart)
    if not client.enabled or not candidates:
        warning = None if client.enabled else "Chưa cấu hình GEMINI_API_KEY - đang dùng gợi ý dự phòng theo nhóm hàng."
        return {**_fallback_cross_sell(cart, candidates), "source": "fallback", "warning": warning, "question": question}
    by_code = {p.code.upper(): p for p in candidates}
    cart_table = "\n".join(f"{p.code} | {p.name} | {p.category.name if p.category else '-'}" for p in cart)
    system, user = render_prompt("cross_sell", cart=cart_table, product_table=product_table(candidates))
    try:
        result = client.generate(system, user, json_mode=True, temperature=0.2, feature="cross_sell")
        data = extract_json(result.text)
    except AIError as e:
        return {**_fallback_cross_sell(cart, candidates), "source": "fallback",
                "warning": f"{e} - chuyển sang gợi ý dự phòng.", "question": question}
    suggestions, removed = [], []
    for s in (data.get("suggestions") or [])[:3]:
        code = str(s.get("code", "")).upper().strip() if isinstance(s, dict) else ""
        p = by_code.get(code)
        if p is None:
            removed.append(code or "?")  # mã bịa, hết hàng, hoặc đã có trong giỏ
        else:
            suggestions.append(_product_dict(p, str(s.get("reason", ""))))
    warning = f"Đã loại bỏ gợi ý không hợp lệ: {', '.join(removed)}" if removed else None
    return {"answer": str(data.get("answer", "")).strip() or "Gợi ý phụ kiện đi kèm:", "suggestions": suggestions,
            "removed": removed, "source": "ai", "warning": warning, "latency_ms": result.latency_ms,
            "model": result.model, "retry_count": result.retries, "question": question}


def _codes_in_text(text: str, by_code: dict[str, Product]) -> list[tuple[str, str]]:
    upper = text.upper()
    found = [(code, upper.find(code)) for code in by_code if re.search(rf"\b{re.escape(code)}\b", upper)]
    found.sort(key=lambda x: x[1])
    return [(code, "") for code, _ in found]


# ---------------------------------------------------------------- 2. Báo cáo doanh thu
REPORT_SECTIONS = ("Tổng quan", "Điểm đáng chú ý", "Rủi ro tồn kho", "Khuyến nghị nhập hàng")  # FR-AIR-03


def _fallback_report(ctx: dict) -> str:
    """Báo cáo theo mẫu, đúng bốn mục bắt buộc, khi chưa cấu hình AI hoặc AI lỗi / sai định dạng."""
    s, prev, cmp_ = ctx["summary"], ctx["previous_period_summary"], ctx.get("comparison") or {}
    lines = ["## Tổng quan",
             f"- Kỳ: {ctx['period']['from']} → {ctx['period']['to']} ({ctx['period']['days']} ngày)",
             f"- Doanh thu: **{fmt_vnd(s['revenue'])}** từ {s['invoice_count']} hóa đơn",
             f"- Lãi gộp ước tính: {fmt_vnd(s['gross_profit'])}"]
    if cmp_.get("growth_percent") is not None:
        lines.append(f"- So với kỳ trước ({fmt_vnd(prev['revenue'])}): {cmp_['growth_percent']:+.1f}%")
    else:
        lines.append("- Kỳ trước chưa có doanh thu để so sánh")
    lines.append("\n## Điểm đáng chú ý")
    for c in ctx["revenue_by_category"][:3]:
        lines.append(f"- Nhóm **{c['category']}**: {fmt_vnd(c['revenue'])} ({c['quantity']} sản phẩm)")
    for p in ctx["top_products"][:3]:
        lines.append(f"- Bán chạy: {p['name']} ({p['quantity']} sp, còn {p['stock']})")
    lines.append("\n## Rủi ro tồn kho")
    if "stock_value" in ctx:
        lines.append(f"- Giá trị tồn kho theo giá vốn: {fmt_vnd(ctx['stock_value'])}")
    for p in ctx["slow_products"][:3]:
        lines.append(f"- Bán chậm: {p['name']} (bán {p['quantity']}, tồn {p['stock']})")
    for p in ctx["low_stock"][:3]:
        lines.append(f"- Sắp hết: {p['name']} (tồn {p['stock']}, mức tối thiểu {p['min_stock']})")
    lines.append("\n## Khuyến nghị nhập hàng")
    if ctx["low_stock"]:
        for p in ctx["low_stock"][:5]:
            need = max(p["min_stock"] * 2 - p["stock"], 1)
            lines.append(f"- Nhập thêm **{p['name']}** khoảng {need} sản phẩm (tồn {p['stock']}, mức tối thiểu {p['min_stock']})")
    else:
        lines.append("- Tồn kho hiện đủ, chưa cần nhập gấp.")
    if ctx["slow_products"]:
        lines.append("- Chưa nhập thêm nhóm bán chậm, cân nhắc khuyến mãi để giải phóng tồn.")
    lines.append("\n> *Báo cáo tự động theo mẫu (chưa cấu hình AI hoặc AI tạm thời lỗi).*")
    return "\n".join(lines)


def _numbers_in(value) -> set[int]:
    if isinstance(value, bool) or value is None:
        return set()
    if isinstance(value, (int, float)):
        return {int(round(value))}
    if isinstance(value, dict):
        return set().union(*(_numbers_in(v) for v in value.values())) if value else set()
    if isinstance(value, (list, tuple)):
        return set().union(*(_numbers_in(v) for v in value)) if value else set()
    return set()


_MONEY_TOKEN = re.compile(r"(?<![\d.,])(\d{1,3}(?:\.\d{3})+|\d{5,})(?![\d])|(\d+(?:,\d+)?)\s*(triệu|tỷ)", re.I)


def report_number_problems(markdown: str, ctx: dict) -> list[str]:
    """FR-AIR-04: các con số tiền trong báo cáo phải có trong dữ liệu đã gửi. Trả về danh sách số không khớp.
    Chỉ kiểm tra số tiền (từ 10.000 trở lên hoặc dạng 'x triệu / x tỷ'); số lượng nhỏ là khuyến nghị của AI."""
    allowed = {abs(n) for n in _numbers_in(ctx)}
    text = re.sub(r"\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}", " ", markdown)  # bỏ ngày tháng
    bad = []
    for m in _MONEY_TOKEN.finditer(text):
        if m.group(1):
            value = int(m.group(1).replace(".", ""))
            if value >= 10_000 and value not in allowed:
                bad.append(m.group(1))
        else:
            value = float(m.group(2).replace(",", ".")) * (1e9 if m.group(3).lower() == "tỷ" else 1e6)
            # "412,4 triệu": chấp nhận nếu làm tròn từ một số trong dữ liệu (sai lệch dưới 1%)
            if not any(n and abs(n - value) <= max(abs(n) * 0.01, 50_000) for n in allowed if n >= 1_000_000):
                bad.append(m.group(0))
    return bad


def _report_problems(markdown: str, ctx: dict) -> list[str]:
    problems = [f"thiếu mục '## {sec}'" for sec in REPORT_SECTIONS
                if not re.search(rf"^#+\s*{re.escape(sec)}\s*$", markdown, re.M | re.I)]
    wrong = report_number_problems(markdown, ctx)
    if wrong:
        problems.append("các con số không có trong dữ liệu: " + ", ".join(wrong[:5]))
    return problems


def sales_report(db: Session, client: GeminiClient, date_from: str | None, date_to: str | None) -> dict:
    start, end = reports.parse_range(date_from, date_to)
    ctx = reports.ai_data_context(db, start, end)
    base = {"data": ctx, "period": ctx["period"]}  # FR-AIR-05: số liệu gốc hiển thị song song nhận xét AI
    if ctx["summary"]["invoice_count"] == 0:
        return {**base, "markdown": "## Tổng quan\nKhông có hóa đơn nào trong kỳ đã chọn, chưa đủ dữ liệu để phân tích.",
                "source": "fallback", "warning": None}
    if not client.enabled:
        return {**base, "markdown": _fallback_report(ctx), "source": "fallback",
                "warning": "Chưa cấu hình GEMINI_API_KEY - đang dùng báo cáo mẫu."}
    system, user = render_prompt(
        "sales_report", date_from=ctx["period"]["from"], date_to=ctx["period"]["to"],
        data_json=json.dumps(ctx, ensure_ascii=False, indent=1),
    )
    retries, latency, problems, markdown, result = 0, 0, [], "", None
    for attempt in range(2):  # sai định dạng hoặc lệch số liệu: thử lại một lần (FR-AIR-04, FR-AIG-05)
        prompt = user if attempt == 0 else (
            user + "\n\nLƯU Ý: báo cáo trước chưa đạt (" + "; ".join(problems) + "). Viết lại đúng bốn mục "
            "bắt buộc và chỉ dùng con số có trong dữ liệu.")
        try:
            result = client.generate(system, prompt, temperature=0.4 if attempt == 0 else 0.1, feature="sales_report")
        except AIError as e:
            if attempt == 0:
                return {**base, "markdown": _fallback_report(ctx), "source": "fallback", "warning": str(e)}
            break
        retries += result.retries + (1 if attempt else 0)
        latency += result.latency_ms
        markdown = re.sub(r"^```(?:markdown)?\s*|\s*```$", "", result.text.strip())
        problems = _report_problems(markdown, ctx)
        if not problems:
            return {**base, "markdown": markdown, "source": "ai", "warning": None, "latency_ms": latency,
                    "model": result.model, "retry_count": retries}
    return {**base, "markdown": _fallback_report(ctx), "source": "fallback", "status": "invalid_format",
            "warning": "Báo cáo AI chưa đạt yêu cầu (" + "; ".join(problems) + "), đã dùng báo cáo mẫu.",
            "ai_markdown": markdown or None, "latency_ms": latency, "retry_count": retries,
            "model": result.model if result else None}


# ---------------------------------------------------------------- 3. Hỏi đáp dữ liệu
def detect_period(question: str, today: date | None = None) -> tuple[date, date, str]:
    """Xác định kỳ dữ liệu từ câu hỏi. Mặc định: tháng này."""
    today = today or now().date()
    q = strip_accents(question)
    month_start = today.replace(day=1)
    if "hom qua" in q:
        d = today - timedelta(days=1)
        return d, d, "hôm qua"
    if "hom nay" in q:
        return today, today, "hôm nay"
    if "thang truoc" in q:
        last_end = month_start - timedelta(days=1)
        return last_end.replace(day=1), last_end, "tháng trước"
    if "tuan nay" in q or "7 ngay" in q or "tuan qua" in q:
        return today - timedelta(days=6), today, "7 ngày gần nhất"
    if "30 ngay" in q:
        return today - timedelta(days=29), today, "30 ngày gần nhất"
    if "quy nay" in q or "3 thang" in q:
        return today - timedelta(days=89), today, "90 ngày gần nhất"
    if "nam nay" in q:
        return today.replace(month=1, day=1), today, "năm nay"
    m = re.search(r"thang\s*(\d{1,2})(?:\D+(\d{4}))?", q)
    if m and 1 <= int(m.group(1)) <= 12:
        month, year = int(m.group(1)), int(m.group(2) or today.year)
        start = date(year, month, 1)
        end = (date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1))
        return start, min(end, today), f"tháng {month}/{year}"
    return month_start, today, "tháng này"


def _fallback_answer(question: str, ctx: dict, label: str) -> str:
    q = strip_accents(question)
    head = ""  # kỳ dữ liệu được giao diện hiển thị thành nhãn riêng dưới câu trả lời
    if "cham" in q or "hang e" in q or "ton nhieu" in q:
        rows = [f"- {p['name']}: bán {p['quantity']}, tồn {p['stock']}" for p in ctx["slow_products"][:5]]
        return head + "Các mặt hàng bán chậm nhất (còn tồn kho):\n" + "\n".join(rows or ["- Không có"])
    if "chay" in q or "nhieu nhat" in q or "top" in q:
        rows = [f"- {p['name']}: {p['quantity']} sp, {fmt_vnd(p['revenue'])}" for p in ctx["top_products"][:5]]
        return head + "Các mặt hàng bán chạy nhất:\n" + "\n".join(rows or ["- Chưa có giao dịch"])
    if "ton" in q or "het hang" in q or "nhap" in q:
        rows = [f"- {p['name']}: còn {p['stock']} (tối thiểu {p['min_stock']})" for p in ctx["low_stock"][:10]]
        return head + "Sản phẩm sắp hết / cần nhập:\n" + "\n".join(rows or ["- Tồn kho đang ổn"])
    if "nhom" in q or "danh muc" in q:
        rows = [f"- {c['category']}: {fmt_vnd(c['revenue'])}" for c in ctx["revenue_by_category"]]
        return head + "Doanh thu theo nhóm hàng:\n" + "\n".join(rows or ["- Chưa có giao dịch"])
    s = ctx["summary"]
    return head + (f"- Doanh thu: {fmt_vnd(s['revenue'])}\n- Số hóa đơn: {s['invoice_count']}\n"
                   f"- Lãi gộp ước tính: {fmt_vnd(s['gross_profit'])}")


def _ask_from_context(db: Session, client: GeminiClient, question: str) -> dict:
    """Cách cũ, dùng khi CSDL không phải SQLite: hệ thống tự tổng hợp số liệu theo kỳ rồi gửi cho AI."""
    d_from, d_to, label = detect_period(question)
    start, end = reports.parse_range(d_from, d_to)
    ctx = reports.ai_data_context(db, start, end)
    base = {"period": ctx["period"], "period_label": label}
    if not client.enabled:
        return {**base, "answer": _fallback_answer(question, ctx, label), "source": "fallback",
                "warning": "Chưa cấu hình GEMINI_API_KEY - đang trả lời theo mẫu."}
    system, user = render_prompt(
        "sales_qa_context", question=question, date_from=ctx["period"]["from"], date_to=ctx["period"]["to"],
        data_json=json.dumps(ctx, ensure_ascii=False, indent=1),
    )
    try:
        result = client.generate(system, user, temperature=0.2, feature="sales_qa")
    except AIError as e:
        return {**base, "answer": _fallback_answer(question, ctx, label), "source": "fallback", "warning": str(e)}
    return {**base, "answer": result.text, "source": "ai", "warning": None, "latency_ms": result.latency_ms,
            "model": result.model}


# ---------------------------------------------------------------- Hỏi đáp bằng text-to-SQL (SRS 6.5)
# Câu SQL mẫu cho chế độ dự phòng (chưa có khóa API): vẫn đi qua đúng bộ kiểm tra và kết nối chỉ đọc.
_FALLBACK_SQL = [
    (("cham", "hang e", "ton nhieu"), "Các mặt hàng bán chậm nhất (còn tồn kho)",
     "SELECT p.name AS san_pham, p.stock_qty AS ton_kho, COALESCE(SUM(s.quantity), 0) AS da_ban\n"
     "FROM v_ai_products p\nLEFT JOIN v_ai_sales_lines s ON s.sku = p.sku AND s.sold_date BETWEEN '{f}' AND '{t}'\n"
     "WHERE p.stock_qty > 0\nGROUP BY p.sku, p.name, p.stock_qty\nORDER BY da_ban ASC, ton_kho DESC\nLIMIT 10"),
    (("chay", "nhieu nhat", "top"), "Các mặt hàng bán chạy nhất",
     "SELECT product_name AS san_pham, SUM(quantity) AS so_luong, SUM(net_revenue) AS doanh_thu\n"
     "FROM v_ai_sales_lines\nWHERE sold_date BETWEEN '{f}' AND '{t}'\nGROUP BY sku, product_name\n"
     "ORDER BY so_luong DESC, doanh_thu DESC\nLIMIT 10"),
    (("het hang", "sap het", "nhap", "ton kho"), "Sản phẩm sắp hết hoặc cần nhập thêm",
     "SELECT name AS san_pham, stock_qty AS ton_kho, min_stock_level AS ton_toi_thieu, sold_30d AS ban_30_ngay\n"
     "FROM v_ai_inventory\nWHERE stock_qty <= min_stock_level\nORDER BY stock_qty ASC, sold_30d DESC"),
    (("nhom", "danh muc", "loai hang"), "Doanh thu theo nhóm hàng",
     "SELECT category AS nhom_hang, SUM(quantity) AS so_luong, SUM(net_revenue) AS doanh_thu\n"
     "FROM v_ai_sales_lines\nWHERE sold_date BETWEEN '{f}' AND '{t}'\nGROUP BY category\nORDER BY doanh_thu DESC"),
    (("khung gio", "cao diem", "theo gio", "gio nao"), "Doanh thu theo khung giờ",
     "SELECT sold_hour AS gio, COUNT(DISTINCT invoice_code) AS so_hoa_don, SUM(net_revenue) AS doanh_thu\n"
     "FROM v_ai_sales_lines\nWHERE sold_date BETWEEN '{f}' AND '{t}'\nGROUP BY sold_hour\nORDER BY doanh_thu DESC"),
    ((), "Tổng hợp doanh thu",
     "SELECT COUNT(DISTINCT invoice_code) AS so_hoa_don, COALESCE(SUM(net_revenue), 0) AS doanh_thu,\n"
     "       COALESCE(SUM(net_revenue - vat_amount - cost_amount), 0) AS lai_gop\n"
     "FROM v_ai_sales_lines\nWHERE sold_date BETWEEN '{f}' AND '{t}'"),
]
_MONEY_COLS = ("doanh_thu", "lai_gop", "revenue", "net_revenue", "gross_profit", "stock_value", "refund", "total",
               "price", "cost", "amount", "tien", "gia")
_COL_VI = {"san_pham": "Sản phẩm", "ton_kho": "tồn", "da_ban": "đã bán", "so_luong": "số lượng", "doanh_thu": "doanh thu",
           "ton_toi_thieu": "tối thiểu", "ban_30_ngay": "bán 30 ngày", "nhom_hang": "Nhóm", "gio": "Giờ",
           "so_hoa_don": "số hóa đơn", "lai_gop": "lãi gộp"}


def _fmt_cell(col: str, value) -> str:
    if isinstance(value, (int, float)) and any(k in col.lower() for k in _MONEY_COLS):
        return fmt_vnd(int(value))
    if isinstance(value, float):
        return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return "" if value is None else str(value)


def format_rows(title: str, columns: list[str], rows: list[list], limit: int = 10) -> str:
    """Viết câu trả lời từ bảng kết quả khi không có AI diễn giải (chế độ dự phòng hoặc AI lỗi ở bước 5)."""
    if not rows:
        return f"{title}: không có dữ liệu phù hợp trong kỳ này."
    if len(rows) == 1 and len(columns) > 1:
        return f"{title}:\n" + "\n".join(f"- {_COL_VI.get(c, c).capitalize()}: {_fmt_cell(c, v)}" for c, v in zip(columns, rows[0]))
    lines = []
    for r in rows[:limit]:
        head = _fmt_cell(columns[0], r[0])
        rest = ", ".join(f"{_COL_VI.get(c, c)} {_fmt_cell(c, v)}" for c, v in zip(columns[1:], r[1:]))
        lines.append(f"- {head}: {rest}" if rest else f"- {head}")
    more = f"\n- ... và {len(rows) - limit} dòng khác (xem bảng kết quả)" if len(rows) > limit else ""
    return f"{title}:\n" + "\n".join(lines) + more


def _table(q: tts.QueryResult) -> dict:
    return {"sql": q.sql, "columns": q.columns, "rows": q.rows, "row_count": len(q.rows), "truncated": q.truncated}


def _ask_fallback(db: Session, question: str, warning: str) -> dict:
    d_from, d_to, label = detect_period(question)
    q = strip_accents(question)
    title, sql = next((t, s) for keys, t, s in _FALLBACK_SQL if not keys or any(k in q for k in keys))
    res = tts.run_sql(db, sql.format(f=d_from.isoformat(), t=d_to.isoformat()))
    return {**_table(res), "answer": format_rows(title, res.columns, res.rows), "source": "fallback", "warning": warning,
            "period": {"from": d_from.isoformat(), "to": d_to.isoformat(), "days": (d_to - d_from).days + 1},
            "period_label": label}


def _gen_sql(client: GeminiClient, question: str, today: date, hint: str, error_block: str = "") -> tuple[dict, AIResult]:
    system, user = render_prompt("sales_sql", schema=tts.VIEW_SCHEMA, today=today.isoformat(), question=question,
                                 period_hint=hint, error_block=error_block)
    result = client.generate(system, user, json_mode=True, temperature=0.0, feature="sales_sql")
    return extract_json(result.text), result


def ask_data(db: Session, client: GeminiClient, question: str) -> dict:
    """UC-47: AI sinh SQL trên view v_ai_*, hệ thống kiểm tra, chạy chỉ đọc, rồi AI diễn giải kết quả."""
    question = scrub(clean_input(question, 500))  # FR-AIG-03: không gửi SĐT, email, số tài khoản cho AI
    if db.get_bind().dialect.name != "sqlite":
        return _ask_from_context(db, client, question)
    if not client.enabled:
        return _ask_fallback(db, question, "Chưa cấu hình GEMINI_API_KEY - đang dùng câu truy vấn mẫu theo từ khóa.")

    today = now().date()
    d_from, d_to, label = detect_period(question)
    hint = f"Gợi ý kỳ dữ liệu: {label} ({d_from.isoformat()} đến {d_to.isoformat()})."
    latency, retries, model = 0, 0, client.model

    # Bước 2: AI sinh SQL; JSON hỏng thì thử lại một lần với lời nhắc định dạng (FR-AIG-05)
    data = r = None
    for attempt in range(2):
        try:
            data, r = _gen_sql(client, question, today, hint, "" if attempt == 0 else FORMAT_REMINDER.strip())
            break
        except AIError as e:
            if e.kind == "bad_response" and attempt == 0:
                retries += 1
                continue
            status = "invalid_format" if e.kind == "bad_response" else None
            out = _ask_fallback(db, question, f"AI lỗi khi sinh truy vấn ({e}); đang dùng câu truy vấn mẫu.")
            return {**out, "retry_count": retries, **({"status": status} if status else {})}
    latency, model = r.latency_ms or 0, r.model
    retries += r.retries
    sql = data.get("sql")
    if not sql:  # AI từ chối hợp lệ: hỏi thông tin cá nhân, ngoài phạm vi...
        reason = str(data.get("reason") or "Câu hỏi nằm ngoài phạm vi dữ liệu bán hàng.")
        return {"answer": f"Mình không trả lời được câu này bằng dữ liệu hệ thống: {reason}\n\n"
                          "Thông tin cá nhân của khách hàng xem tại màn hình Khách hàng.",
                "sql": None, "source": "ai", "warning": None, "latency_ms": latency, "model": model}

    # Bước 3, 4: kiểm tra và chạy; lỗi cú pháp cho AI sửa đúng một lần (FR-AIQ-08)
    res = None
    for attempt in range(2):
        try:
            res = tts.run_sql(db, sql)
            break
        except tts.SQLRejected as e:
            return {"answer": f"Câu hỏi này cần truy vấn ngoài phạm vi cho phép nên hệ thống không chạy ({e}). "
                              "Bạn thử diễn đạt lại, ví dụ hỏi về doanh thu, sản phẩm, tồn kho hoặc nhập hàng.",
                    "sql": sql, "source": "ai", "status": "rejected_sql", "warning": str(e),
                    "latency_ms": latency, "model": model, "retry_count": retries}
        except tts.SQLTimeout as e:
            return {"answer": "Truy vấn chạy quá lâu nên đã dừng. Bạn thử thu hẹp kỳ dữ liệu hoặc hỏi cụ thể hơn.",
                    "sql": sql, "source": "fallback", "status": "timeout", "warning": str(e),
                    "latency_ms": latency, "model": model, "retry_count": retries}
        except sqlite3.Error as e:
            if attempt == 1:
                return {"answer": "AI chưa viết được câu truy vấn đúng cho câu hỏi này. Bạn thử diễn đạt lại rõ hơn.",
                        "sql": sql, "source": "fallback", "status": "error", "warning": f"Lỗi SQL: {e}",
                        "latency_ms": latency, "model": model, "retry_count": retries}
            retries += 1
            err = f"Câu SQL trước bị lỗi khi chạy:\n```sql\n{sql}\n```\nThông báo lỗi: {e}\nHãy sửa lại."
            try:
                data, r = _gen_sql(client, question, today, hint, err)
            except AIError as ae:
                return {"answer": "AI không sửa được câu truy vấn. Bạn thử hỏi lại sau.", "sql": sql,
                        "source": "fallback", "warning": str(ae), "latency_ms": latency, "model": model,
                        "retry_count": retries}
            latency += r.latency_ms or 0
            sql = data.get("sql") or ""

    table = _table(res)
    # Bước 5: AI diễn giải kết quả (không có thông tin cá nhân trong view)
    rows_json = json.dumps([dict(zip(res.columns, row)) for row in res.rows], ensure_ascii=False, default=str)
    system, user = render_prompt("sales_qa", question=question, today=today.isoformat(), sql=res.sql,
                                 row_count=len(res.rows), rows_json=rows_json)
    try:
        r = client.generate(system, user, temperature=0.2, feature="sales_qa")
    except AIError as e:
        return {**table, "answer": format_rows("Kết quả truy vấn", res.columns, res.rows), "source": "fallback",
                "warning": f"AI chưa diễn giải được kết quả ({e}), đang hiển thị kết quả thô.",
                "latency_ms": latency, "model": model, "retry_count": retries}
    return {**table, "answer": r.text, "source": "ai", "warning": None, "latency_ms": latency + (r.latency_ms or 0),
            "model": r.model, "retry_count": retries}
