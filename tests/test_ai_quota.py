"""Test hạn mức Gemini: tự chuyển model dự phòng khi hết lượt / quá tải, thông báo rõ, không thử lại vô ích."""
import json
from datetime import datetime, timezone

import httpx
import pytest

from app.ai.client import AIError, GeminiClient, next_quota_reset

OK = {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}


def quota_429(per_day=True, delay="31s"):
    """Phản hồi 429 đúng định dạng Google: QuotaFailure (loại hạn mức) + RetryInfo (số giây nên đợi)."""
    quota = "GenerateRequestsPerDayPerProjectPerModel-FreeTier" if per_day else "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"
    return httpx.Response(429, json={"error": {"code": 429, "message": "You exceeded your current quota", "details": [
        {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [{"quotaId": quota, "quotaValue": "20"}]},
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": delay}]}})


class Clock:
    """Đồng hồ giả: 03:56 sáng 24/09/2026 giờ Việt Nam."""

    def __init__(self):
        self.t = datetime(2026, 9, 23, 20, 56, tzinfo=timezone.utc).timestamp()

    def __call__(self):
        return self.t


def model_of(req: httpx.Request) -> str:
    return req.url.path.split("/models/")[1].split(":")[0]


def make(handler, models=("a", "b", "c"), retries=2, clock=None, thinking_level="low"):
    return GeminiClient(api_key="k", model=models[0], fallback_models=list(models[1:]), timeout=1, max_retries=retries,
                        transport=httpx.MockTransport(handler), clock=clock or Clock(), thinking_level=thinking_level)


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    monkeypatch.setattr("app.ai.client.time.sleep", lambda s: None)
    monkeypatch.setattr("app.ai.client.GeminiClient._log", staticmethod(lambda *a: None))


def test_daily_quota_switches_model_and_remembers():
    calls = []

    def handler(req):
        calls.append(model_of(req))
        return quota_429() if calls[-1] == "a" else httpx.Response(200, json=OK)

    c = make(handler)
    assert c.generate("s", "u").model == "b"
    assert calls == ["a", "b"]  # hết lượt ngày: không thử lại model a
    c.generate("s", "u")
    assert calls == ["a", "b", "b"]  # câu hỏi sau bỏ qua luôn model a
    st = c.status()
    assert st["active_model"] == "b"
    assert st["models"][0]["reason"] == "day" and st["models"][0]["until"]


def test_minute_limit_rests_only_for_retry_delay():
    clock, calls = Clock(), []

    def handler(req):
        calls.append(model_of(req))
        return quota_429(per_day=False, delay="31s") if calls.count("a") == 1 and calls[-1] == "a" else httpx.Response(200, json=OK)

    c = make(handler, clock=clock)
    assert c.generate("s", "u").model == "b"
    clock.t += 10
    assert c.generate("s", "u").model == "b"  # a vẫn đang nghỉ
    clock.t += 30
    assert c.generate("s", "u").model == "a"  # quá 31 giây: quay lại model chính


def test_all_models_out_for_the_day_gives_clear_message():
    calls = []

    def handler(req):
        calls.append(model_of(req))
        return quota_429()

    c = make(handler, models=("a", "b"))
    with pytest.raises(AIError) as e:
        c.generate("s", "u")
    assert e.value.kind == "quota_day"
    reset = datetime.fromtimestamp(next_quota_reset(Clock()()).timestamp()).strftime("%H:%M")
    assert "hết lượt gọi AI miễn phí hôm nay của cả 2 model" in str(e.value) and reset in str(e.value)
    with pytest.raises(AIError):
        c.generate("s", "u")
    assert calls == ["a", "b"]  # mọi model đang nghỉ: không gửi thêm yêu cầu nào
    assert c.status()["active_model"] is None


def test_minute_limit_message_when_no_other_model():
    c = make(lambda req: quota_429(per_day=False, delay="42s"), models=("a",))
    with pytest.raises(AIError) as e:
        c.generate("s", "u")
    assert e.value.kind == "rate_limit" and "42 giây" in str(e.value)


def test_overloaded_model_switches_immediately():
    calls = []

    def handler(req):
        calls.append(model_of(req))
        return httpx.Response(503, json={"error": {"message": "high demand"}}) if calls[-1] == "a" else httpx.Response(200, json=OK)

    c = make(handler, retries=2)
    assert c.generate("s", "u").model == "b"
    assert calls == ["a", "b"]  # 503 quá tải: chuyển model ngay, không thử lại
    assert c.status()["models"][0]["reason"] == "busy"


def test_timeout_switches_immediately():
    calls = []

    def handler(req):
        calls.append(model_of(req))
        if calls[-1] == "a":
            raise httpx.ReadTimeout("slow", request=req)
        return httpx.Response(200, json=OK)

    c = make(handler, retries=2)
    assert c.generate("s", "u").model == "b"
    assert calls == ["a", "b"]  # timeout: không chờ thêm lần nữa
    assert c.status()["models"][0]["reason"] == "busy"


def test_other_server_error_retries_then_switches():
    calls = []

    def handler(req):
        calls.append(model_of(req))
        return httpx.Response(500, json={"error": {"message": "internal"}}) if calls[-1] == "a" else httpx.Response(200, json=OK)

    c = make(handler, retries=1)
    assert c.generate("s", "u").model == "b"
    assert calls == ["a", "a", "b"]  # 5xx khác: thử lại cùng model theo cấu hình rồi mới chuyển
    assert c.status()["models"][0]["reason"] == "busy"


def test_thinking_level_is_sent():
    sent = []

    def handler(req):
        sent.append(json.loads(req.content)["generationConfig"])
        return httpx.Response(200, json=OK)

    make(handler, thinking_level="low").generate("s", "u")
    make(handler, thinking_level="").generate("s", "u")
    assert sent[0]["thinkingConfig"] == {"thinkingLevel": "low"}
    assert "thinkingConfig" not in sent[1]  # để trống: theo mặc định của model


def test_model_rejecting_thinking_level_is_resent_without_it():
    sent = []

    def handler(req):
        config = json.loads(req.content)["generationConfig"]
        sent.append("thinkingConfig" in config)
        if "thinkingConfig" in config:
            return httpx.Response(400, json={"error": {"message": "Thinking level is not supported for this model."}})
        return httpx.Response(200, json=OK)

    c = make(handler, thinking_level="minimal")
    assert c.generate("s", "u").model == "a"
    c.generate("s", "u")
    assert sent == [True, False, False]  # gửi lại không kèm tùy chọn và nhớ cho lần sau


def test_discontinued_model_is_skipped():
    def handler(req):
        if model_of(req) == "a":
            return httpx.Response(404, json={"error": {"message": "This model is no longer available to new users"}})
        return httpx.Response(200, json=OK)

    c = make(handler)
    assert c.generate("s", "u").model == "b"
    m = c.status()["models"][0]
    assert (m["reason"], m["until"]) == ("gone", None)


def test_invalid_key_does_not_try_other_models():
    calls = []

    def handler(req):
        calls.append(model_of(req))
        return httpx.Response(400, json={"error": {"message": "API key not valid"}})

    with pytest.raises(AIError) as e:
        make(handler).generate("s", "u")
    assert e.value.kind == "config" and calls == ["a"]


def test_chat_pins_model_and_keeps_call_id():
    calls = []
    fc = {"candidates": [{"content": {"role": "model", "parts": [
        {"functionCall": {"name": "search_products", "args": {"keyword": "loa"}, "id": "call_1"}}]}}]}

    def handler(req):
        calls.append(model_of(req))
        return httpx.Response(200, json=fc)

    c = make(handler)
    r = c.chat("s", [{"role": "user", "parts": [{"text": "loa?"}]}], tools=[{"name": "search_products", "description": "d"}])
    assert r.calls == [{"name": "search_products", "args": {"keyword": "loa"}, "id": "call_1"}] and r.model == "a"
    c._rest("a", 60, "minute")  # model ghim đang nghỉ vẫn được gọi đúng model đó, không tự đổi giữa câu hỏi
    c.chat("s", [{"role": "user", "parts": [{"text": "loa?"}]}], tools=[], model="a")
    assert calls == ["a", "a"]


@pytest.mark.parametrize("utc,expected", [
    (datetime(2026, 9, 23, 20, 56, tzinfo=timezone.utc), datetime(2026, 9, 24, 7, 0, tzinfo=timezone.utc)),   # giờ mùa hè (PDT)
    (datetime(2026, 12, 10, 12, 0, tzinfo=timezone.utc), datetime(2026, 12, 11, 8, 0, tzinfo=timezone.utc)),  # giờ mùa đông (PST)
    (datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc), datetime(2026, 3, 9, 7, 0, tzinfo=timezone.utc)),      # ngay sau khi đổi giờ
])
def test_next_quota_reset_is_pacific_midnight(utc, expected):
    assert next_quota_reset(utc.timestamp()) == expected


# ---------------- Trợ lý đa năng ----------------
def test_assistant_restarts_on_other_model_when_quota_runs_out_mid_question(client, owner_h, fake_ai):
    fake_ai.chat_script = [[{"name": "list_categories", "args": {}, "id": "c1"}],
                           AIError("Model fake-model đã hết lượt gọi miễn phí hôm nay", "quota_day"),
                           "Cửa hàng có 1 nhóm hàng"]
    body = client.post("/api/ai/assistant", json={"message": "Có mấy nhóm hàng?"}, headers=owner_h).json()
    assert body["source"] == "ai" and body["answer"] == "Cửa hàng có 1 nhóm hàng"
    assert [c["model"] for c in fake_ai.calls] == [None, "fake-model", None]  # vòng 2 ghim model, lỗi -> làm lại từ đầu
    sent = [p["functionResponse"] for c in fake_ai.calls[1]["contents"] for p in c["parts"] if "functionResponse" in p]
    assert sent[0]["id"] == "c1"  # trả lại id lệnh gọi công cụ
    assert not any("functionResponse" in p for c in fake_ai.calls[2]["contents"] for p in c["parts"])
    assert body["model"] == "fake-model"


def test_assistant_keeps_switching_models_until_one_answers(client, owner_h, fake_ai):
    """Model 3.6 rồi 3.8 lần lượt hết lượt giữa chừng: vẫn làm lại trên model kế tiếp, không rơi về dự phòng."""
    call = [{"name": "list_categories", "args": {}}]
    out = AIError("Model hết lượt gọi miễn phí hôm nay", "quota_day")
    fake_ai.chat_script = [call, out, call, out, "Cửa hàng có 1 nhóm hàng"]
    body = client.post("/api/ai/assistant", json={"message": "Có mấy nhóm hàng?"}, headers=owner_h).json()
    assert body["source"] == "ai" and body["answer"] == "Cửa hàng có 1 nhóm hàng"
    assert len(fake_ai.calls) == 5


def test_assistant_falls_back_when_no_model_left(client, owner_h, fake_ai):
    fake_ai.available = False
    fake_ai.chat_script = [[{"name": "list_categories", "args": {}}],
                           AIError("Đã dùng hết lượt gọi AI miễn phí hôm nay của cả 4 model", "quota_day")]
    body = client.post("/api/ai/assistant", json={"message": "Có mấy nhóm hàng?"}, headers=owner_h).json()
    assert body["source"] == "fallback" and "hết lượt" in body["warning"]
    assert len(fake_ai.calls) == 2  # không làm lại khi không còn model nào


def test_status_reports_active_model(client, owner_h, fake_ai):
    s = client.get("/api/ai/status", headers=owner_h).json()
    assert s["model"] == "fake-model" and s["models"][0]["available"]
    fake_ai.available = False
    assert client.get("/api/ai/status", headers=owner_h).json()["model"] is None


def test_invalid_key_explains_how_to_fix_and_stops():
    """401/403 từ Google (key sai / đã xóa): báo rõ là do GEMINI_API_KEY, không thử model khác vô ích."""
    calls = []

    def handler(req):
        calls.append(model_of(req))
        return httpx.Response(401, json={"error": {"code": 401, "status": "UNAUTHENTICATED",
                                                   "message": "Request had invalid authentication credentials. Expected OAuth 2 access token"}})

    with pytest.raises(AIError) as e:
        make(handler).generate("sys", "hi")
    assert "GEMINI_API_KEY" in str(e.value) and "OAuth" not in str(e.value)
    assert e.value.kind == "config"
    assert calls == ["a"]
