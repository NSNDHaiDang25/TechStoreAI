"""Test lịch sử tra cứu AI: lưu hội thoại, ngữ cảnh nhiều lượt, tìm kiếm, đổi tên, xóa, quyền riêng tư."""
import json


def advise(client, h, message, session_id=None):
    body = {"message": message}
    if session_id:
        body["session_id"] = session_id
    r = client.post("/api/ai/advisor", json=body, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def test_first_message_creates_session_with_title(client, staff_h, fake_ai):
    fake_ai.response = json.dumps({"answer": "Gợi ý A1", "suggestions": [{"code": "PK001", "reason": "pin"}]})
    res = advise(client, staff_h, "Khách cần tai nghe pin lâu")
    assert res["session_id"] and res["session_title"] == "Khách cần tai nghe pin lâu"
    sessions = client.get("/api/ai/sessions", params={"kind": "advisor"}, headers=staff_h).json()
    assert [(s["id"], s["message_count"]) for s in sessions] == [(res["session_id"], 2)]


def test_follow_up_reuses_session_and_sends_context(client, staff_h, fake_ai):
    fake_ai.response = json.dumps({"answer": "Có tai nghe A1 giá 350k", "suggestions": []})
    first = advise(client, staff_h, "Tai nghe dưới 500k")
    second = advise(client, staff_h, "Còn màu khác không?", first["session_id"])
    assert second["session_id"] == first["session_id"]
    prompt = fake_ai.calls[1]["user"]
    assert "Tai nghe dưới 500k" in prompt and "Có tai nghe A1 giá 350k" in prompt  # nhớ ngữ cảnh lượt trước
    detail = client.get(f"/api/ai/sessions/{first['session_id']}", headers=staff_h).json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant", "user", "assistant"]


def test_history_keeps_suggestions_and_source(client, staff_h, fake_ai):
    fake_ai.response = json.dumps({"answer": "ok", "suggestions": [{"code": "PK003", "reason": "sạc nhanh"}]})
    res = advise(client, staff_h, "sạc nhanh")
    msg = client.get(f"/api/ai/sessions/{res['session_id']}", headers=staff_h).json()["messages"][1]
    assert msg["meta"]["source"] == "ai"
    assert msg["meta"]["suggestions"][0]["code"] == "PK003"
    assert "image_url" in msg["meta"]["suggestions"][0]  # đủ dữ liệu để hiển thị lại thẻ sản phẩm khi mở lịch sử


def test_search_rename_delete(client, staff_h, fake_ai):
    a = advise(client, staff_h, "Tai nghe chống ồn")
    b = advise(client, staff_h, "Loa đi du lịch")
    found = client.get("/api/ai/sessions", params={"kind": "advisor", "q": "loa"}, headers=staff_h).json()
    assert [s["id"] for s in found] == [b["session_id"]]
    r = client.patch(f"/api/ai/sessions/{a['session_id']}", json={"title": "Tư vấn tai nghe"}, headers=staff_h)
    assert r.json()["title"] == "Tư vấn tai nghe"
    assert client.delete(f"/api/ai/sessions/{a['session_id']}", headers=staff_h).status_code == 200
    remaining = client.get("/api/ai/sessions", params={"kind": "advisor"}, headers=staff_h).json()
    assert [s["id"] for s in remaining] == [b["session_id"]]
    assert client.delete("/api/ai/sessions", params={"kind": "advisor"}, headers=staff_h).json()["deleted"] == 1


def test_users_cannot_see_each_others_history(client, staff_h, owner_h):
    res = advise(client, staff_h, "Tai nghe")
    sid = res["session_id"]
    assert client.get(f"/api/ai/sessions/{sid}", headers=owner_h).status_code == 404
    assert client.delete(f"/api/ai/sessions/{sid}", headers=owner_h).status_code == 404
    assert client.get("/api/ai/sessions", params={"kind": "advisor"}, headers=owner_h).json() == []
    # Không thể "chen" tin nhắn vào cuộc trò chuyện của người khác
    r = client.post("/api/ai/advisor", json={"message": "x", "session_id": sid}, headers=owner_h)
    assert r.status_code == 404


def test_ask_history_is_separate_and_manager_only(client, owner_h, staff_h, fake_ai):
    fake_ai.response = "Doanh thu ổn"
    r = client.post("/api/ai/ask", json={"question": "Doanh thu tháng này?"}, headers=owner_h).json()
    assert r["session_id"]
    ask_sessions = client.get("/api/ai/sessions", params={"kind": "ask"}, headers=owner_h).json()
    assert [s["id"] for s in ask_sessions] == [r["session_id"]]
    assert client.get("/api/ai/sessions", params={"kind": "advisor"}, headers=owner_h).json() == []
    msg = client.get(f"/api/ai/sessions/{r['session_id']}", headers=owner_h).json()["messages"][1]
    assert msg["meta"]["period_label"] == "tháng này"
    assert client.get("/api/ai/sessions", params={"kind": "ask"}, headers=staff_h).status_code == 403
    # session của hỏi đáp không dùng được cho chatbot tư vấn
    assert client.post("/api/ai/advisor", json={"message": "x", "session_id": r["session_id"]}, headers=owner_h).status_code == 404


def test_long_title_is_truncated(client, staff_h):
    res = advise(client, staff_h, "tai nghe " * 30)
    assert len(res["session_title"]) <= 60 and res["session_title"].endswith("...")


def test_admin_reads_all_conversations_read_only(client, staff_h, owner_h, admin_h, fake_ai):
    fake_ai.response = json.dumps({"answer": "Gợi ý A1", "suggestions": []})
    mine = advise(client, staff_h, "Khách cần tai nghe pin lâu")
    advise(client, owner_h, "Sạc nhanh cho iPhone")
    r = client.get("/api/ai/conversations", headers=admin_h)
    assert r.status_code == 200 and r.json()["total"] == 2
    assert {i["user_role"] for i in r.json()["items"]} == {"staff", "owner"}
    found = client.get("/api/ai/conversations", params={"q": "tai nghe"}, headers=admin_h).json()["items"]
    assert [i["id"] for i in found] == [mine["session_id"]] and found[0]["user_name"] == "Nhân viên"
    detail = client.get(f"/api/ai/conversations/{mine['session_id']}", headers=admin_h).json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"] and detail["user_role"] == "staff"
    # Chỉ quản trị viên xem được; quản trị viên không sửa, xóa được hội thoại của người khác
    assert client.get("/api/ai/conversations", headers=owner_h).status_code == 403
    assert client.get("/api/ai/conversations", headers=staff_h).status_code == 403
    assert client.delete(f"/api/ai/sessions/{mine['session_id']}", headers=admin_h).status_code == 403
    assert client.post("/api/ai/advisor", json={"message": "hi"}, headers=admin_h).status_code == 403
