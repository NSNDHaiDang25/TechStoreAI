"""Test chức năng AI với client giả (không gọi mạng): kiểm soát dữ liệu đầu vào và lỗi phản hồi."""
import json
from datetime import date

import httpx
import pytest

from app.ai import service
from app.ai.client import AIError, GeminiClient
from app.ai.prompts import load_prompt, render
from tests.helpers import product_id


# ---------------- Chatbot tư vấn ----------------
# TC-AIA-03 (SRS 11.3)
def test_advisor_v3_sends_only_in_stock_products(client, staff_h, fake_ai):
    fake_ai.response = json.dumps({"answer": "Gợi ý A1", "suggestions": [{"code": "PK001", "reason": "Pin 20 giờ"}]})
    r = client.post("/api/ai/advisor?version=v3", json={"message": "tai nghe dưới 500k pin lâu"}, headers=staff_h)
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "ai"
    assert [s["code"] for s in body["suggestions"]] == ["PK001"]
    sent = fake_ai.calls[0]["user"]
    assert "PK001" in sent and "PK002" not in sent  # PK002 hết hàng không được gửi
    assert fake_ai.calls[0]["json_mode"] is True


# TC-AIA-04 (SRS 11.3)
def test_advisor_removes_out_of_stock_and_unknown_suggestions(client, staff_h, fake_ai):
    fake_ai.response = json.dumps({"answer": "...", "suggestions": [
        {"code": "PK002", "reason": "chống ồn"},     # hết hàng
        {"code": "XX999", "reason": "bịa"},           # không tồn tại
        {"code": "pk001", "reason": "pin 20 giờ"},    # hợp lệ (chữ thường vẫn nhận)
    ]})
    body = client.post("/api/ai/advisor", json={"message": "tai nghe"}, headers=staff_h).json()
    assert [s["code"] for s in body["suggestions"]] == ["PK001"]
    assert set(body["removed"]) == {"PK002", "XX999"}
    assert body["warning"]


def test_advisor_handles_json_in_code_fence(client, staff_h, fake_ai):
    fake_ai.response = '```json\n{"answer": "ok", "suggestions": [{"code": "PK003", "reason": "sạc"}]}\n```'
    body = client.post("/api/ai/advisor", json={"message": "sạc nhanh"}, headers=staff_h).json()
    assert [s["code"] for s in body["suggestions"]] == ["PK003"]


def test_advisor_handles_malformed_response(client, staff_h, fake_ai):
    fake_ai.response = "Bạn nên mua PK001 hoặc PK002 nhé"  # không phải JSON
    body = client.post("/api/ai/advisor", json={"message": "tai nghe"}, headers=staff_h).json()
    assert body["answer"].startswith("Bạn nên mua")
    assert [s["code"] for s in body["suggestions"]] == ["PK001"]
    assert body["removed"] == ["PK002"]


# TC-AIA-05 (SRS 11.3)
@pytest.mark.parametrize("kind", ["timeout", "rate_limit", "bad_response"])
def test_advisor_falls_back_on_ai_error(client, staff_h, fake_ai, kind):
    fake_ai.response = AIError("lỗi giả lập", kind)
    r = client.post("/api/ai/advisor", json={"message": "tai nghe dưới 500000"}, headers=staff_h)
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "fallback"
    codes = [s["code"] for s in body["suggestions"]]
    assert "PK002" not in codes and "PK001" in codes


# TC-AIA-05 (SRS 11.3)
def test_fallback_when_ai_disabled(client, staff_h, fake_ai):
    fake_ai.enabled = False
    body = client.post("/api/ai/advisor", json={"message": "sạc điện thoại"}, headers=staff_h).json()
    assert body["source"] == "fallback"
    assert [s["code"] for s in body["suggestions"]] == ["PK003"]
    assert fake_ai.calls == []


def test_fallback_respects_budget(db):
    products = service._active_products(db)
    res = service._fallback_advise(products, "tai nghe dưới 300k")
    assert res["suggestions"] == []  # A1 giá 350k vượt ngân sách, A2 hết hàng


def test_advisor_rejects_empty_or_too_long_message(client, staff_h):
    assert client.post("/api/ai/advisor", json={"message": ""}, headers=staff_h).status_code == 422
    assert client.post("/api/ai/advisor", json={"message": "a" * 1001}, headers=staff_h).status_code == 422


def test_advisor_v1_detects_out_of_stock_in_free_text(client, staff_h, fake_ai):
    fake_ai.response = "Gợi ý: PK002 - Tai nghe A2 Pro chống ồn tốt nhất."
    body = client.post("/api/ai/advisor?version=v1", json={"message": "tai nghe"}, headers=staff_h).json()
    assert body["suggestions"] == [] and body["removed"] == ["PK002"]
    assert "PK002" in fake_ai.calls[0]["user"]  # v1 gửi cả hàng hết -> dễ tư vấn sai


# ---------------- Báo cáo AI ----------------
def sell(client, h, code, qty):
    pid = product_id(client, h, code)
    client.post("/api/invoices", json={"items": [{"product_id": pid, "quantity": qty}], "customer_id": 1}, headers=h)


# TC-AIR-03 (SRS 11.3)
def test_ai_report_does_not_leak_customer_pii(client, owner_h, fake_ai):
    sell(client, owner_h, "PK001", 2)
    fake_ai.response = ("## Tổng quan\nDoanh thu tốt.\n## Điểm đáng chú ý\n- A1 bán chạy\n"
                        "## Rủi ro tồn kho\n- Ổn\n## Khuyến nghị nhập hàng\n- Nhập thêm A1")
    body = client.post("/api/ai/report", json={}, headers=owner_h).json()
    assert body["source"] == "ai"
    assert body["markdown"].startswith("## Tổng quan")
    prompt = fake_ai.calls[0]["user"]
    assert "0901234567" not in prompt and "Phạm Minh Anh" not in prompt
    assert "700000" in prompt  # số liệu doanh thu có trong dữ liệu gửi đi


# TC-AIR-01 (SRS 11.3)
def test_ai_report_falls_back_on_bad_format(client, owner_h, fake_ai):
    sell(client, owner_h, "PK001", 1)
    fake_ai.response = "ok"  # không có tiêu đề Markdown
    body = client.post("/api/ai/report", json={}, headers=owner_h).json()
    assert body["source"] == "fallback"
    assert "## Tổng quan" in body["markdown"]


def test_ai_report_without_data_skips_ai(client, owner_h, fake_ai):
    body = client.post("/api/ai/report", json={}, headers=owner_h).json()
    assert "chưa đủ dữ liệu" in body["markdown"]
    assert fake_ai.calls == []


def test_ai_report_fallback_on_timeout(client, owner_h, fake_ai):
    sell(client, owner_h, "PK001", 1)
    fake_ai.response = AIError("timeout", "timeout")
    body = client.post("/api/ai/report", json={}, headers=owner_h).json()
    assert body["source"] == "fallback" and "Khuyến nghị nhập hàng" in body["markdown"]


# ---------------- Hỏi đáp dữ liệu ----------------
# TC-AIQ-01 (SRS 11.3)
def test_ask_data_uses_system_data(client, owner_h, fake_ai):
    """UC-47: AI sinh SQL trên view, hệ thống chạy rồi gửi bảng kết quả cho AI diễn giải."""
    sell(client, owner_h, "PK003", 4)
    sql = ("SELECT p.name, p.stock_qty, COALESCE(SUM(s.quantity), 0) AS sold FROM v_ai_products p "
           "LEFT JOIN v_ai_sales_lines s ON s.sku = p.sku WHERE p.stock_qty > 0 GROUP BY p.name, p.stock_qty ORDER BY sold")
    fake_ai.responses = [json.dumps({"sql": sql}), "Tháng này Tai nghe Bluetooth A1 bán chậm."]
    body = client.post("/api/ai/ask", json={"question": "Tháng này mặt hàng nào bán chậm?"}, headers=owner_h).json()
    assert body["answer"] == "Tháng này Tai nghe Bluetooth A1 bán chậm."
    assert body["columns"] == ["name", "stock_qty", "sold"]
    assert body["rows"][0] == ["Tai nghe Bluetooth A1", 12, 0] and body["sql"].startswith("SELECT p.name")
    assert "v_ai_sales_lines" in fake_ai.calls[0]["system"] and fake_ai.calls[0]["json_mode"]
    assert "Tai nghe Bluetooth A1" in fake_ai.calls[1]["user"]  # bảng kết quả gửi cho AI diễn giải


def test_ask_data_fallback_slow_products(client, owner_h, fake_ai):
    fake_ai.enabled = False
    sell(client, owner_h, "PK003", 4)
    body = client.post("/api/ai/ask", json={"question": "Mặt hàng nào bán chậm?"}, headers=owner_h).json()
    assert "Tai nghe Bluetooth A1" in body["answer"]


@pytest.mark.parametrize("question,label,start", [
    ("Doanh thu hôm nay?", "hôm nay", date(2026, 5, 20)),
    ("Tháng trước bán được bao nhiêu", "tháng trước", date(2026, 4, 1)),
    ("7 ngày qua thế nào", "7 ngày gần nhất", date(2026, 5, 14)),
    ("tháng 3 doanh thu", "tháng 3/2026", date(2026, 3, 1)),
    ("mặt hàng bán chạy", "tháng này", date(2026, 5, 1)),
])
def test_detect_period(question, label, start):
    d_from, _, got_label = service.detect_period(question, today=date(2026, 5, 20))
    assert (got_label, d_from) == (label, start)


# ---------------- Tiện ích & client ----------------
def test_mask_phone():
    assert service.mask_phone("0901234567") == "090****567"


@pytest.mark.parametrize("text,budget", [
    ("dưới 500000 đồng", 500_000), ("tầm 500k", 500_000), ("1,5 triệu", 1_500_000),
    ("2tr", 2_000_000), ("500.000đ", 500_000), ("tai nghe pin lâu", None),
])
def test_parse_budget(text, budget):
    assert service.parse_budget(text) == budget


# FR-AIG-01
def test_prompt_files_render():
    for name in ["product_advisor_v1", "product_advisor_v2", "product_advisor_v3", "sales_report", "sales_qa", "sales_sql", "sales_qa_context"]:
        system, user = load_prompt(name)
        assert system and user
    with pytest.raises(KeyError):
        render("{{missing}}")


def _client_with(handler, retries=1, fallbacks=()):
    return GeminiClient(api_key="test", model="m", timeout=1, max_retries=retries,
                        transport=httpx.MockTransport(handler), fallback_models=list(fallbacks))


def test_gemini_client_parses_response(monkeypatch):
    monkeypatch.setattr("app.ai.client.GeminiClient._log", staticmethod(lambda *a: None))
    ok = {"candidates": [{"content": {"parts": [{"text": "xin chào"}]}}]}
    res = _client_with(lambda req: httpx.Response(200, json=ok)).generate("s", "u")
    assert res.text == "xin chào"


def test_gemini_client_rate_limit_switches_model_without_retrying(monkeypatch):
    monkeypatch.setattr("app.ai.client.time.sleep", lambda s: None)
    monkeypatch.setattr("app.ai.client.GeminiClient._log", staticmethod(lambda *a: None))
    calls = []

    def handler(req):
        calls.append(req.url.path.split("/models/")[1].split(":")[0])
        if calls[-1] == "m":
            return httpx.Response(429, json={"error": {"message": "quota"}})
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]})

    res = _client_with(handler, retries=2, fallbacks=["m2"]).generate("s", "u")
    assert (res.text, res.model) == ("ok", "m2")
    assert calls == ["m", "m2"]  # 429 không thử lại cùng model (chỉ tốn thêm lượt), chuyển model ngay


# TC-AIG-02 (SRS 11.3)
def test_gemini_client_timeout(monkeypatch):
    monkeypatch.setattr("app.ai.client.time.sleep", lambda s: None)
    monkeypatch.setattr("app.ai.client.GeminiClient._log", staticmethod(lambda *a: None))

    def handler(req):
        raise httpx.ReadTimeout("slow")

    with pytest.raises(AIError) as e:
        _client_with(handler).generate("s", "u")
    assert e.value.kind == "timeout"


# TC-AIG-04 (SRS 11.3)
def test_gemini_client_bad_format(monkeypatch):
    monkeypatch.setattr("app.ai.client.GeminiClient._log", staticmethod(lambda *a: None))
    with pytest.raises(AIError) as e:
        _client_with(lambda req: httpx.Response(200, json={"unexpected": True})).generate("s", "u")
    assert e.value.kind == "bad_response"


def test_gemini_client_auth_error_not_retried(monkeypatch):
    monkeypatch.setattr("app.ai.client.GeminiClient._log", staticmethod(lambda *a: None))
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(400, json={"error": {"message": "API key not valid"}})

    with pytest.raises(AIError) as e:
        _client_with(handler, retries=3).generate("s", "u")
    assert e.value.kind == "config" and len(calls) == 1


def test_fallback_advise_ignores_budget_numbers(db):
    """'20 triệu' không được khớp nhầm sản phẩm có '20' trong tên (Sạc nhanh 20W)."""
    products = service._active_products(db)
    picks = service._fallback_advise(products, "tai nghe dưới 20 triệu")["suggestions"]
    assert picks and all(p["name"].startswith("Tai nghe") for p in picks)
    assert service._fallback_advise(products, "sạc 20W")["suggestions"][0]["code"] == "PK003"


def test_assistant_fallback_tool_label_matches_answer(client, owner_h, fake_ai):
    fake_ai.enabled = False
    body = client.post("/api/ai/assistant", json={"message": "Sản phẩm nào sắp hết hàng cần nhập?"}, headers=owner_h).json()
    assert [t["name"] for t in body["tools"]] == ["inventory_report"]
