"""Trợ lý AI đa năng: một khung chat trả lời được nhiều loại câu hỏi.

- Dữ liệu cửa hàng (sản phẩm, tồn kho, hóa đơn, khách hàng, doanh thu...): Gemini tự chọn và gọi các công cụ
  chỉ-đọc trong app/ai/tools.py (function calling), có thể gọi nhiều lượt, rồi trả lời dựa trên kết quả.
- Cách dùng phần mềm: công cụ app_guide (prompts/app_guide.md).
- Kiến thức / kỹ năng chung: AI trả lời bằng kiến thức của mình.
Khi chưa có API key hoặc AI lỗi: bộ định tuyến rule-based chọn công cụ theo từ khóa.
"""
import re

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.ai import tools
from app.ai.client import AIError, GeminiClient
from app.ai.prompts import render_prompt
from app.ai.sanitizer import scrub
from app.ai.service import (_active_products, _fallback_advise, _fallback_answer, _product_dict, clean_input,
                            detect_period, fmt_vnd, strip_accents)
from app.config import settings
from app.models import Product, User, now
from app.services import reports

MAX_ROUNDS = 5           # số vòng gọi công cụ tối đa cho một câu hỏi, vòng cuối buộc trả lời bằng văn bản
MAX_CALLS_PER_ROUND = 6  # số công cụ tối đa thực thi trong một vòng
MAX_CARDS = 4
# Lỗi mà đổi sang model khác có thể khắc phục (hết lượt, quá tải, mạng chậm)
SWITCHABLE = ("quota_day", "rate_limit", "error", "timeout")
MAX_MODEL_SWITCHES = 4   # số lần làm lại câu hỏi trên model khác khi model đang dùng hết lượt giữa chừng
ROLE_VI = {"admin": "Quản trị viên", "owner": "Chủ cửa hàng", "staff": "Nhân viên bán hàng"}


def _prompt_vars(user: User) -> dict:
    today = now().date()
    manager = tools.is_manager(user)
    return {
        "shop_name": settings.SHOP_NAME, "user_name": user.full_name, "role_label": ROLE_VI.get(user.role, user.role),
        "today": today.strftime("%d/%m/%Y (%Y-%m-%d)"), "weekday": tools.WEEKDAYS_VI[today.weekday()],
        "manager_scope": (", doanh thu, lợi nhuận, xu hướng bán hàng, bán chạy / bán chậm, tồn kho, nhập hàng, "
                          "khách hàng thân thiết" if manager else ""),
        "role_rules": ("- Người dùng là quản lý, được xem toàn bộ số liệu kinh doanh." if manager else
                       "- Vai trò nhân viên KHÔNG xem được doanh thu toàn cửa hàng, lợi nhuận, giá vốn, báo cáo tồn kho, "
                       "lịch sử nhập hàng và chỉ tra được hóa đơn do chính mình lập. Nếu được hỏi những dữ liệu này, "
                       "lịch sự trả lời rằng chức năng chỉ dành cho chủ cửa hàng."),
    }


def _history_contents(history: list[dict]) -> list[dict]:
    out = [{"role": "user" if m.get("role") == "user" else "model",
            "parts": [{"text": scrub(clean_input(str(m.get("content", "")), 2000))}]} for m in history]
    while out and out[0]["role"] == "model":  # hội thoại gửi cho Gemini phải bắt đầu bằng lượt của người dùng
        out.pop(0)
    return out


def _product_codes(result: dict) -> set[str]:
    """Mã sản phẩm xuất hiện trong kết quả công cụ tra sản phẩm (dòng có giá bán = thông tin sản phẩm)."""
    rows = [result, *(result.get("items") or []), *(result.get("matches") or [])]
    return {r["code"] for r in rows if isinstance(r, dict) and "code" in r and "price" in r}


def _cards(db: Session, answer: str, allowed: set[str]) -> list[dict]:
    """Thẻ sản phẩm cho các mã AI nhắc tới trong câu trả lời, chỉ khi mã đó đến từ kết quả tra cứu và còn hàng."""
    if not allowed:
        return []
    upper = answer.upper()
    found = sorted((upper.find(c), c) for c in allowed if re.search(rf"\b{re.escape(c)}\b", upper))
    codes = [c for _, c in found]
    by_code = {p.code: p for p in db.scalars(select(Product).options(joinedload(Product.category))
                                             .where(Product.code.in_(codes)))}
    cards = [by_code[c] for c in codes if c in by_code and by_code[c].status == "active" and by_code[c].stock > 0]
    return [_product_dict(p) for p in cards[:MAX_CARDS]]


def reply(db: Session, client: GeminiClient, user: User, message: str, history: list[dict] | None = None) -> dict:
    message = clean_input(message)
    if not client.enabled:
        return {**fallback(db, user, message), "source": "fallback",
                "warning": "Chưa cấu hình GEMINI_API_KEY - trợ lý đang chạy chế độ dự phòng, chỉ hiểu các câu hỏi cơ bản."}

    # FR-AIG-03 / BR-42: số điện thoại, email, dãy số dài trong câu hỏi không được gửi cho AI
    system, user_text = render_prompt("assistant", message=scrub(message), **_prompt_vars(user))
    declarations = tools.declarations(tools.available(user))
    contents = _history_contents(history or []) + [{"role": "user", "parts": [{"text": user_text}]}]
    for attempt in range(MAX_MODEL_SWITCHES + 1):
        try:
            r, used, product_codes, latency = _tool_loop(db, client, user, system, contents, declarations)
            break
        except AIError as e:
            # Model đang dùng hết lượt / quá tải GIỮA CHỪNG câu hỏi: làm lại câu hỏi từ đầu trên model khác
            # (chữ ký suy luận của model này không dùng được cho model khác nên không thể nối tiếp).
            # Model lỗi đã bị cho nghỉ nên mỗi lần làm lại rơi vào model kế tiếp trong chuỗi dự phòng.
            if (attempt < MAX_MODEL_SWITCHES and getattr(e, "mid_loop", False) and e.kind in SWITCHABLE
                    and client.has_available_model()):
                continue
            return {**fallback(db, user, message), "source": "fallback", "warning": f"{e} - chuyển sang trả lời dự phòng."}

    answer = r.text or "Xin lỗi, mình chưa tìm được câu trả lời phù hợp. Bạn thử hỏi cụ thể hơn nhé."
    return {"answer": answer, "suggestions": _cards(db, answer, product_codes),
            "tools": [{"name": k, "label": v} for k, v in used.items()],
            "source": "ai", "warning": None, "latency_ms": latency, "model": r.model}


def _tool_loop(db: Session, client: GeminiClient, user: User, system: str, contents: list[dict], declarations: list[dict]):
    """Vòng gọi công cụ cho một câu hỏi. Model được ghim sau vòng đầu để các vòng sau dùng cùng model."""
    contents = list(contents)
    used: dict[str, str] = {}
    product_codes: set[str] = set()
    latency, model = 0, None
    for round_no in range(MAX_ROUNDS + 1):
        last = round_no == MAX_ROUNDS
        try:
            r = client.chat(system, contents, tools=declarations, temperature=0.3, force_text=last,
                            feature="assistant", model=model)
        except AIError as e:
            e.mid_loop = model is not None
            raise
        model = r.model
        latency += r.latency_ms
        if not r.calls or last:
            return r, used, product_codes, latency
        contents.append(r.content)
        parts = []
        for i, call in enumerate(r.calls):
            if i < MAX_CALLS_PER_ROUND:
                result = tools.run(db, user, call["name"], call["args"])
            else:
                result = {"error": "Quá nhiều lệnh gọi công cụ trong một lượt, hãy gộp bớt."}
            if call["name"] in tools.TOOLS:
                used.setdefault(call["name"], tools.TOOLS[call["name"]].label)
            product_codes |= _product_codes(result)
            response = {"name": call["name"], "response": result}
            if call.get("id"):
                response["id"] = call["id"]  # model Gemini 3 gắn id cho từng lệnh gọi, trả lại để ghép đúng cặp
            parts.append({"functionResponse": response})
        contents.append({"role": "user", "parts": parts})


# ---------------------------------------------------------------- Dự phòng rule-based
_GUIDE_HINTS = ("lam sao", "lam the nao", "the nao de", "bang cach nao", "cach nao", "huong dan", "o dau",
                "cach de", "cach tao", "cach huy", "cach sua", "cach xem", "cach in", "cach nhap", "cach them")
_REPORT_HINTS = ("doanh thu", "loi nhuan", "lai gop", "bao cao", "ban chay", "ban cham", "ban duoc bao nhieu")
_STOCK_HINTS = ("ton kho", "sap het", "het hang", "nhap them", "can nhap", "nhom hang", "danh muc")


def _used(*names: str) -> list[dict]:
    return [{"name": n, "label": tools.TOOLS[n].label} for n in names]


def _help_text(user: User) -> str:
    lines = ["Trợ lý đang ở **chế độ dự phòng** nên chỉ hiểu một số câu hỏi cơ bản, ví dụ:",
             "- Tìm sản phẩm: *\"tai nghe dưới 500k\"*, *\"PK001 còn hàng không\"*",
             "- Tra hóa đơn theo mã: *\"HD-20261001-0001\"*",
             "- Hướng dẫn: *\"làm sao để hủy hóa đơn\"*"]
    if tools.is_manager(user):
        lines.append("- Số liệu: *\"doanh thu tháng này\"*, *\"mặt hàng bán chạy\"*, *\"sản phẩm sắp hết\"*, "
                     "*\"khách mua nhiều nhất\"*")
    lines.append("\nKhi cấu hình GEMINI_API_KEY, bạn có thể hỏi tự do mọi câu hỏi.")
    return "\n".join(lines)


def _invoice_answer(db: Session, user: User, code: str) -> dict:
    res = tools.run(db, user, "find_invoices", {"keyword": code})
    if not res.get("invoices"):
        extra = " (nhân viên chỉ xem được hóa đơn do mình lập)" if user.role == "staff" else ""
        return {"answer": f"Không tìm thấy hóa đơn **{code}**{extra}.", "tools": _used("find_invoices")}
    inv = res["invoices"][0]
    lines = [f"**Hóa đơn {inv['code']}** ({inv['status']})", f"- Thời gian: {inv['time']}",
             f"- Khách hàng: {inv['customer']}", f"- Nhân viên: {inv['staff']}", "- Sản phẩm:",
             *[f"  - {x}" for x in inv["items"]]]
    if inv["discount"]:
        lines.append(f"- Giảm giá: {fmt_vnd(inv['discount'])}")
    lines.append(f"- Tổng tiền: **{fmt_vnd(inv['total'])}** ({inv['payment_method']})")
    if inv["cancel_reason"]:
        lines.append(f"- Lý do hủy: {inv['cancel_reason']}")
    return {"answer": "\n".join(lines), "tools": _used("find_invoices")}


def _product_answer(db: Session, user: User, p: Product) -> dict:
    d = tools.run(db, user, "get_product", {"code_or_name": p.code})
    lines = [f"**{d['name']}** ({d['code']}){' - ' + d['category'] if d['category'] else ''}",
             f"- Giá bán: **{fmt_vnd(d['price'])}**", f"- Tồn kho: {d['stock']} ({d['stock_state']}, {d['status']})",
             f"- Đã bán 30 ngày qua: {d['sold_last_30_days']}"]
    if "cost_price" in d:
        lines.append(f"- Giá vốn: {fmt_vnd(d['cost_price'])} · biên lãi {d['margin_percent']}%")
    if d["description"]:
        lines.append(f"- Mô tả: {d['description']}")
    cards = [_product_dict(p)] if p.status == "active" and p.stock > 0 else []
    return {"answer": "\n".join(lines), "suggestions": cards, "tools": _used("get_product")}


def fallback(db: Session, user: User, message: str) -> dict:
    """Chọn công cụ theo từ khóa khi không dùng được Gemini. Trả về answer, suggestions, tools (+ kỳ dữ liệu)."""
    q = strip_accents(message)
    manager = tools.is_manager(user)
    base = {"suggestions": [], "tools": []}

    m = re.search(r"\bhd-?\d{8}-?\d{3,}\b|\bhd\d{6,}\b", q)  # HD-20261001-0001 (mới) hoặc HD2605200001 (cũ)
    if m:
        code = m.group(0).upper()
        if "-" not in code and len(code) == 14:
            code = f"{code[:2]}-{code[2:10]}-{code[10:]}"
        return {**base, **_invoice_answer(db, user, code)}

    if any(h in q for h in _GUIDE_HINTS):
        res = tools.run(db, user, "app_guide", {"topic": message})
        if res.get("sections"):
            return {**base, "answer": "\n\n".join("### " + s for s in res["sections"][:2]), "tools": _used("app_guide")}

    wants_report = any(h in q for h in _REPORT_HINTS)
    if wants_report and not manager:
        return {**base, "answer": "Số liệu doanh thu, lợi nhuận và báo cáo bán hàng chỉ dành cho chủ cửa hàng. "
                                  "Bạn có thể xem các hóa đơn do mình lập ở menu **Hóa đơn**."}
    if manager and "khach" in q and any(h in q for h in ("mua nhieu", "than thiet", "top", "chi tieu")):
        d_from, d_to, label = detect_period(message)
        res = tools.run(db, user, "top_customers", {"date_from": d_from.isoformat(), "date_to": d_to.isoformat()})
        rows = [f"{i}. {c['name']} ({c['code']}, {c['group']}): {fmt_vnd(c['total_spent'])} / {c['invoice_count']} hóa đơn"
                for i, c in enumerate(res["customers"], 1)]
        return {**base, "answer": "Khách hàng chi tiêu nhiều nhất:\n" + "\n".join(rows or ["- Chưa có giao dịch"]),
                "tools": _used("top_customers"), "period": res["period"], "period_label": label}
    if manager and (wants_report or any(h in q for h in _STOCK_HINTS)):
        d_from, d_to, label = detect_period(message)
        start, end = reports.parse_range(d_from, d_to)
        ctx = reports.ai_data_context(db, start, end)
        # Nhãn công cụ khớp với nhánh _fallback_answer đã chọn (trước đây luôn ghi "Doanh thu tổng hợp")
        if "cham" in q or "hang e" in q or "ton nhieu" in q or "chay" in q or "nhieu nhat" in q or "top" in q:
            used = "product_sales_ranking"
        elif "ton" in q or "het hang" in q or "nhap" in q:
            used = "inventory_report"
        elif "nhom" in q or "danh muc" in q:
            used = "revenue_breakdown"
        else:
            used = "sales_summary"
        return {**base, "answer": _fallback_answer(message, ctx, label), "tools": _used(used),
                "period": ctx["period"], "period_label": label}

    products = _active_products(db)
    by_code = {p.code.lower(): p for p in products}
    for code in re.findall(r"\b[a-z]{2}\d{3}\b", q):
        if code in by_code:
            return {**base, **_product_answer(db, user, by_code[code])}

    advice = _fallback_advise(products, message)
    if advice["suggestions"]:
        return {**base, **advice, "tools": _used("search_products")}
    return {**base, "answer": _help_text(user)}
