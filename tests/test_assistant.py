"""Test trợ lý AI đa năng: vòng gọi công cụ (function calling), phân quyền công cụ, bảo mật dữ liệu, chế độ dự phòng."""
import json

import httpx
import pytest

from app.ai import assistant, tools
from app.ai.client import AIError, GeminiClient
from app.ai.prompts import render_prompt
from app.models import User
from tests.helpers import product_id


def ask(client, h, message, session_id=None):
    body = {"message": message}
    if session_id:
        body["session_id"] = session_id
    r = client.post("/api/ai/assistant", json=body, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def sell(client, h, code, qty, customer_id=1):
    pid = product_id(client, h, code)
    r = client.post("/api/invoices", json={"items": [{"product_id": pid, "quantity": qty}], "customer_id": customer_id},
                    headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def tool_results(call):
    """Kết quả công cụ (functionResponse) đã gửi lại cho AI trong một lượt gọi."""
    return {p["functionResponse"]["name"]: p["functionResponse"]["response"]
            for c in call["contents"] for p in c["parts"] if "functionResponse" in p}


def user_of(db, username):
    db.expire_all()  # đọc lại dữ liệu API vừa ghi
    return db.query(User).filter_by(username=username).one()


# ---------------- Vòng gọi công cụ ----------------
def test_assistant_calls_tools_and_shows_product_cards(client, staff_h, fake_ai):
    fake_ai.chat_script = [
        [{"name": "search_products", "args": {"keyword": "tai nghe", "max_price": 500000}}],
        "Mình gợi ý Tai nghe Bluetooth A1 (PK001) giá 350.000 ₫, pin 20 giờ.",
    ]
    body = ask(client, staff_h, "Khách cần tai nghe dưới 500k")
    assert body["source"] == "ai" and body["answer"].startswith("Mình gợi ý")
    assert [s["code"] for s in body["suggestions"]] == ["PK001"]
    assert body["tools"] == [{"name": "search_products", "label": "Tìm sản phẩm"}]
    result = tool_results(fake_ai.calls[1])["search_products"]
    assert [p["code"] for p in result["items"]] == ["PK001"]  # PK002 hết hàng không được trả về
    assert fake_ai.calls[0]["feature"] == "assistant"


def test_cards_only_for_looked_up_in_stock_products(client, staff_h, fake_ai):
    fake_ai.chat_script = [
        [{"name": "search_products", "args": {"keyword": "tai nghe", "in_stock_only": False}}],
        "PK002 đã hết hàng, bạn có thể lấy PK001. Ngoài ra có PK003.",
    ]
    body = ask(client, staff_h, "tai nghe chống ồn")
    # PK002 hết hàng, PK003 AI tự nhắc mà không tra cứu => không hiện thẻ
    assert [s["code"] for s in body["suggestions"]] == ["PK001"]


def test_tool_loop_is_bounded(client, owner_h, fake_ai):
    fake_ai.chat_script = [[{"name": "list_categories", "args": {}}]] * assistant.MAX_ROUNDS + ["Xong"]
    body = ask(client, owner_h, "Liệt kê nhóm hàng")
    assert body["answer"] == "Xong"
    assert len(fake_ai.calls) == assistant.MAX_ROUNDS + 1
    assert fake_ai.calls[-1]["force_text"] is True and not any(c["force_text"] for c in fake_ai.calls[:-1])


def test_follow_up_sends_history_as_turns(client, staff_h, fake_ai):
    fake_ai.chat_script = ["Tai nghe A1 giá 350.000 ₫", "Còn 12 chiếc"]
    first = ask(client, staff_h, "Giá tai nghe A1?")
    second = ask(client, staff_h, "Còn bao nhiêu cái?", first["session_id"])
    assert second["session_id"] == first["session_id"]
    contents = fake_ai.calls[1]["contents"]
    assert [c["role"] for c in contents] == ["user", "model", "user"]
    assert contents[1]["parts"][0]["text"] == "Tai nghe A1 giá 350.000 ₫"
    sessions = client.get("/api/ai/sessions", params={"kind": "assistant"}, headers=staff_h).json()
    assert [s["id"] for s in sessions] == [first["session_id"]]
    msg = client.get(f"/api/ai/sessions/{first['session_id']}", headers=staff_h).json()["messages"][1]
    assert msg["meta"]["source"] == "ai" and "tools" in msg["meta"]


def test_ai_error_falls_back(client, staff_h, fake_ai):
    fake_ai.chat_script = [AIError("timeout", "timeout")]
    body = ask(client, staff_h, "tai nghe pin lâu")
    assert body["source"] == "fallback" and body["warning"]
    assert [s["code"] for s in body["suggestions"]] == ["PK001"]


# ---------------- Phân quyền và bảo mật ----------------
def test_staff_cannot_use_manager_tools(client, staff_h, owner_h, fake_ai):
    sell(client, owner_h, "PK001", 2)
    fake_ai.chat_script = [[{"name": "sales_summary", "args": {}}], "Chức năng này chỉ dành cho chủ cửa hàng."]
    ask(client, staff_h, "Doanh thu tháng này?")
    declared = {t["name"] for t in fake_ai.calls[0]["tools"]}
    assert "sales_summary" not in declared and "search_products" in declared
    res = tool_results(fake_ai.calls[1])["sales_summary"]
    assert "error" in res and "700000" not in json.dumps(res)
    assert "Nhân viên bán hàng" in fake_ai.calls[0]["system"]


def test_find_invoices_respects_staff_scope(client, owner_h, staff_h, db):
    own = sell(client, staff_h, "PK003", 1)
    other = sell(client, owner_h, "PK001", 1)
    staff = user_of(db, "staff")
    assert [i["code"] for i in tools.run(db, staff, "find_invoices", {})["invoices"]] == [own["code"]]
    assert tools.run(db, staff, "find_invoices", {"keyword": other["code"]})["matched_count"] == 0
    res = tools.run(db, user_of(db, "owner"), "find_invoices", {"order": "largest"})
    assert res["matched_count"] == 2 and res["invoices"][0]["code"] == other["code"]


def test_customer_tools_mask_phone(client, owner_h, db):
    sell(client, owner_h, "PK001", 2)
    owner = user_of(db, "owner")
    c = tools.run(db, owner, "find_customers", {"keyword": "Minh Anh"})["customers"][0]
    assert c["phone_masked"] == "090****567" and c["total_spent"] == 700000
    top = tools.run(db, owner, "top_customers", {})
    assert top["customers"][0]["code"] == "KH0001"
    assert "0901234567" not in json.dumps(top)


def test_get_product_hides_cost_from_staff(db):
    assert "cost_price" not in tools.run(db, user_of(db, "staff"), "get_product", {"code_or_name": "pk001"})
    d = tools.run(db, user_of(db, "owner"), "get_product", {"code_or_name": "Tai nghe A1"})
    assert d["code"] == "PK001" and d["cost_price"] == 220000


# ---------------- Công cụ tra cứu ----------------
def test_owner_sales_summary_tool(client, owner_h, fake_ai):
    sell(client, owner_h, "PK001", 2)
    sell(client, owner_h, "PK003", 1, customer_id=None)
    fake_ai.chat_script = [[{"name": "sales_summary", "args": {}}], "Doanh thu tháng này 890.000 ₫"]
    ask(client, owner_h, "Doanh thu tháng này?")
    res = tool_results(fake_ai.calls[1])["sales_summary"]
    assert res["summary"]["revenue"] == 890000 and res["summary"]["invoice_count"] == 2
    assert res["summary"]["average_invoice"] == 445000
    assert res["period"]["from"].endswith("-01")
    assert res["by_payment_method"] == [{"method": "Tiền mặt", "invoice_count": 2, "revenue": 890000}]


@pytest.mark.parametrize("group_by", ["day", "month", "category", "payment_method", "staff", "hour", "weekday"])
def test_revenue_breakdown_group_by(client, owner_h, db, group_by):
    sell(client, owner_h, "PK001", 1)
    res = tools.run(db, user_of(db, "owner"), "revenue_breakdown", {"group_by": group_by})
    assert "error" not in res, res
    assert sum(r["revenue"] for r in res["rows"]) == 350000


def test_import_and_stock_history(client, owner_h, db):
    pid = product_id(client, owner_h, "PK001")
    r = client.post("/api/imports", json={"supplier": "NCC Minh Long",
                                          "items": [{"product_id": pid, "quantity": 5, "unit_cost": 200000}]},
                    headers=owner_h)
    assert r.status_code == 201, r.text
    owner = user_of(db, "owner")
    imp = tools.run(db, owner, "import_history", {"product": "PK001"})
    assert imp["receipt_count"] == 1 and imp["total_value"] == 1_000_000
    assert "giá nhập 200.000 ₫" in imp["receipts"][0]["items"][0]
    move = tools.run(db, owner, "stock_history", {"product": "PK001"})["movements"][0]
    assert (move["type"], move["change"], move["stock_after"]) == ("Nhập hàng", 5, 17)


@pytest.mark.parametrize("name,args", [
    ("search_products", {}), ("search_products", {"category": "phu kien", "sort": "price_desc"}),
    ("get_product", {"code_or_name": "PK003"}), ("list_categories", {}), ("find_invoices", {"status": "paid"}),
    ("find_customers", {"group": "vip"}), ("app_guide", {"topic": "nhập hàng"}),
    ("sales_summary", {"date_from": "2026-01-01"}), ("product_sales_ranking", {"order": "slow"}),
    ("inventory_report", {"filter": "out"}), ("top_customers", {}), ("stock_history", {"product": "PK001"}),
    ("import_history", {}),
])
def test_every_tool_runs(client, owner_h, db, name, args):
    sell(client, owner_h, "PK001", 1)
    res = tools.run(db, user_of(db, "owner"), name, args)
    assert "error" not in res, res


def test_tool_errors_are_returned_not_raised(db):
    owner = user_of(db, "owner")
    assert "YYYY-MM-DD" in tools.run(db, owner, "sales_summary", {"date_from": "tháng trước"})["error"]
    assert "error" in tools.run(db, owner, "revenue_breakdown", {"group_by": "year"})
    assert "error" in tools.run(db, owner, "revenue_breakdown",
                                {"group_by": "day", "date_from": "2025-01-01", "date_to": "2025-12-31"})
    assert "error" in tools.run(db, owner, "no_such_tool", {})
    assert "error" in tools.run(db, owner, "get_product", {"code_or_name": "xyz999"})


def test_declarations_and_prompt(db):
    staff, owner = user_of(db, "staff"), user_of(db, "owner")
    decls = tools.declarations(tools.available(owner))
    assert len(decls) == len(tools.TOOLS)
    assert len(tools.declarations(tools.available(staff))) < len(decls)
    for d in decls:
        params = d.get("parameters", {"properties": {}, "required": []})
        assert set(params["required"]) <= set(params["properties"])
        assert all(p["type"] in {"STRING", "INTEGER", "BOOLEAN"} for p in params["properties"].values())
    system, user = render_prompt("assistant", message="xin chào", **assistant._prompt_vars(staff))
    assert "chỉ dành cho chủ cửa hàng" in system and user == "xin chào"


# ---------------- Chế độ dự phòng (không có API key) ----------------
def test_fallback_routes_by_intent(client, owner_h, staff_h, fake_ai):
    fake_ai.enabled = False
    inv = sell(client, owner_h, "PK003", 4)

    guide = ask(client, staff_h, "Làm sao để hủy hóa đơn?")
    assert "Hủy hóa đơn" in guide["answer"] and guide["tools"][0]["name"] == "app_guide"
    revenue = ask(client, owner_h, "Doanh thu tháng này thế nào?")
    assert "760.000" in revenue["answer"] and revenue["period_label"] == "tháng này"
    denied = ask(client, staff_h, "Doanh thu tháng này?")
    assert "chỉ dành cho chủ cửa hàng" in denied["answer"]
    invoice = ask(client, owner_h, f"Xem hóa đơn {inv['code']}")
    assert inv["code"] in invoice["answer"] and "760.000" in invoice["answer"]
    product = ask(client, staff_h, "PK001 còn hàng không?")
    assert "Tồn kho: 12" in product["answer"] and product["suggestions"][0]["code"] == "PK001"
    unknown = ask(client, staff_h, "xin chào")
    assert "chế độ dự phòng" in unknown["answer"] and unknown["source"] == "fallback"
    assert fake_ai.calls == []


# ---------------- Client Gemini ----------------
def test_gemini_chat_parses_function_calls(monkeypatch):
    monkeypatch.setattr("app.ai.client.GeminiClient._log", staticmethod(lambda *a: None))
    sent = []
    replies = [
        {"candidates": [{"content": {"role": "model", "parts": [
            {"functionCall": {"name": "search_products", "args": {"keyword": "loa"}}, "thoughtSignature": "abc"}]}}]},
        {"candidates": [{"content": {"role": "model", "parts": [{"text": "Có loa M1"}]}}]},
    ]

    def handler(req):
        sent.append(json.loads(req.content))
        return httpx.Response(200, json=replies[len(sent) - 1])

    c = GeminiClient(api_key="k", model="m", timeout=1, max_retries=0, transport=httpx.MockTransport(handler),
                     fallback_models=[])
    contents = [{"role": "user", "parts": [{"text": "loa?"}]}]
    decl = [{"name": "search_products", "description": "d"}]
    r = c.chat("sys", contents, tools=decl)
    assert r.calls == [{"name": "search_products", "args": {"keyword": "loa"}}] and r.text == ""
    assert r.content["parts"][0]["thoughtSignature"] == "abc"  # gửi lại nguyên vẹn ở lượt sau
    assert sent[0]["tools"][0]["functionDeclarations"] == decl
    assert sent[0]["toolConfig"]["functionCallingConfig"]["mode"] == "AUTO"
    r2 = c.chat("sys", contents, tools=decl, force_text=True)
    assert r2.text == "Có loa M1" and r2.calls == []
    assert sent[1]["toolConfig"]["functionCallingConfig"]["mode"] == "NONE"


def test_gemini_chat_empty_response_is_error(monkeypatch):
    monkeypatch.setattr("app.ai.client.GeminiClient._log", staticmethod(lambda *a: None))
    empty = {"candidates": [{"content": {"parts": []}, "finishReason": "SAFETY"}]}
    c = GeminiClient(api_key="k", model="m", timeout=1, max_retries=0, fallback_models=[],
                     transport=httpx.MockTransport(lambda req: httpx.Response(200, json=empty)))
    with pytest.raises(AIError) as e:
        c.chat("sys", [{"role": "user", "parts": [{"text": "x"}]}], tools=[])
    assert e.value.kind == "bad_response" and "SAFETY" in str(e.value)
