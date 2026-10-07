"""Module hệ thống: khóa đăng nhập, thu hồi token, đổi mật khẩu, cấu hình, audit log, nhật ký AI, sao lưu."""
from tests.conftest import _login


def login(client, username, password):
    return client.post("/api/auth/login", json={"username": username, "password": password})


# ---------------------------------------------------------------- AUT
# FR-AUT-04
def test_wrong_username_and_wrong_password_get_same_message(client):
    a = login(client, "khong-co", "owner123")
    b = login(client, "owner", "sai-mat-khau1")
    assert a.status_code == b.status_code == 401
    assert a.json()["detail"] == b.json()["detail"]


# TC-AUT-01 (SRS 11.3)
def test_account_locked_after_5_failures_then_admin_unlocks(client, admin_h):
    for _ in range(4):
        assert login(client, "staff", "sai-mat-khau1").status_code == 401
    r = login(client, "staff", "sai-mat-khau1")
    assert r.status_code == 423 and "15 phút" in r.json()["detail"]
    assert login(client, "staff", "staff123").status_code == 423  # đúng mật khẩu vẫn bị khóa
    logs = client.get("/api/audit-logs", params={"action": "LOGIN_FAILED"}, headers=admin_h).json()
    assert logs["total"] == 5
    staff_id = next(u["id"] for u in client.get("/api/users", headers=admin_h).json() if u["username"] == "staff")
    client.put(f"/api/users/{staff_id}", json={"unlock": True}, headers=admin_h)
    assert login(client, "staff", "staff123").status_code == 200


def test_success_resets_failure_counter(client):
    for _ in range(4):
        login(client, "staff", "sai-mat-khau1")
    assert login(client, "staff", "staff123").status_code == 200
    for _ in range(4):
        assert login(client, "staff", "sai-mat-khau1").status_code == 401  # đếm lại từ đầu


# TC-AUT-03 (SRS 11.3)
def test_logout_revokes_token(client):
    h = _login(client, "staff", "staff123")
    assert client.get("/api/auth/me", headers=h).status_code == 200
    assert client.post("/api/auth/logout", headers=h).status_code == 200
    assert client.get("/api/auth/me", headers=h).status_code == 401
    assert client.get("/api/products", headers=h).status_code == 401
    other = _login(client, "staff", "staff123")  # phiên mới không bị ảnh hưởng
    assert client.get("/api/auth/me", headers=other).status_code == 200


def test_new_user_must_change_password_first(client, admin_h):
    r = client.post("/api/users", json={"username": "nv3", "full_name": "Nhân viên 3", "password": "TamThoi123",
                                        "role": "staff", "email": "nv3@example.com"}, headers=admin_h)
    assert r.status_code == 201 and r.json()["must_change_password"] is True
    h = _login(client, "nv3", "TamThoi123")
    assert client.get("/api/products", headers=h).status_code == 403
    assert client.get("/api/auth/me", headers=h).json()["must_change_password"] is True
    weak = client.post("/api/auth/change-password", json={"old_password": "TamThoi123", "new_password": "abcdefgh"},
                       headers=h)
    assert weak.status_code == 422
    wrong = client.post("/api/auth/change-password", json={"old_password": "sai", "new_password": "MoiMoi123"},
                        headers=h)
    assert wrong.status_code == 400
    ok = client.post("/api/auth/change-password", json={"old_password": "TamThoi123", "new_password": "MoiMoi123"},
                     headers=h)
    assert ok.status_code == 200
    assert client.get("/api/products", headers=h).status_code == 200
    assert login(client, "nv3", "MoiMoi123").status_code == 200


# FR-USR-01
def test_password_policy_on_create(client, admin_h):
    for pw in ("ngan1", "chicochu", "12345678"):
        r = client.post("/api/users", json={"username": "x" + pw, "full_name": "X", "password": pw}, headers=admin_h)
        assert r.status_code == 422, pw


# FR-USR-03
def test_admin_reset_password_forces_change(client, admin_h):
    staff_id = next(u["id"] for u in client.get("/api/users", headers=admin_h).json() if u["username"] == "staff")
    r = client.post(f"/api/users/{staff_id}/reset-password", json={"new_password": "DatLai2026"}, headers=admin_h)
    assert r.status_code == 200
    h = _login(client, "staff", "DatLai2026")
    assert client.get("/api/invoices", headers=h).status_code == 403


# FR-USR-03, FR-USR-05
def test_role_change_is_audited(client, admin_h):
    staff_id = next(u["id"] for u in client.get("/api/users", headers=admin_h).json() if u["username"] == "staff")
    client.put(f"/api/users/{staff_id}", json={"role": "owner"}, headers=admin_h)
    logs = client.get("/api/audit-logs", params={"action": "ROLE_CHANGE"}, headers=admin_h).json()["items"]
    assert len(logs) == 1 and '"staff"' in logs[0]["old_value"] and '"owner"' in logs[0]["new_value"]


# ---------------------------------------------------------------- Cấu hình
def keys_of(resp):
    return {i["key"]: i for i in resp.json()["items"]}


def test_owner_edits_business_settings_only(client, owner_h):
    items = keys_of(client.get("/api/settings", headers=owner_h))
    assert items["low_stock_threshold"]["value"] == 5 and items["low_stock_threshold"]["editable"]
    assert "ai_enabled" not in items
    r = client.put("/api/settings", json={"values": {"return_window_hours": 48}}, headers=owner_h)
    assert r.status_code == 200 and r.json()["updated"] == ["return_window_hours"]
    assert keys_of(client.get("/api/settings", headers=owner_h))["return_window_hours"]["value"] == 48
    assert client.put("/api/settings", json={"values": {"ai_enabled": False}}, headers=owner_h).status_code == 403
    logs = client.get("/api/audit-logs", headers=owner_h).json()["items"]
    assert logs[0]["action"] == "SETTINGS_UPDATE_OWNER"


def test_settings_validation(client, owner_h, admin_h, staff_h):
    assert client.put("/api/settings", json={"values": {"points_max_percent": 150}}, headers=owner_h).status_code == 400
    assert client.put("/api/settings", json={"values": {"khong_co": 1}}, headers=owner_h).status_code == 403
    assert client.put("/api/settings", json={"values": {"ai_prompt_version": "v9"}}, headers=admin_h).status_code == 400
    assert client.put("/api/settings", json={"values": {"tier_silver_min": 90_000_000}},
                      headers=owner_h).status_code == 400  # Bạc phải nhỏ hơn Vàng
    assert client.put("/api/settings", json={"values": {"low_stock_threshold": 3}}, headers=staff_h).status_code == 403
    assert all(not i["editable"] for i in client.get("/api/settings", headers=staff_h).json()["items"])


def test_tier_thresholds_sync_with_settings(client, owner_h):
    client.put("/api/settings", json={"values": {"tier_silver_min": 10_000_000}}, headers=owner_h)
    tiers = client.get("/api/customer-tiers", headers=owner_h).json()
    assert next(t for t in tiers if t["name"] == "Bạc")["min_total_spent"] == 10_000_000


def test_owner_sees_only_business_audit_logs(client, owner_h, admin_h):
    login(client, "staff", "sai-mat-khau1")  # log kỹ thuật
    client.put("/api/settings", json={"values": {"low_stock_threshold": 3}}, headers=owner_h)
    owner_actions = {i["action"] for i in client.get("/api/audit-logs", headers=owner_h).json()["items"]}
    admin_actions = {i["action"] for i in client.get("/api/audit-logs", headers=admin_h).json()["items"]}
    assert "LOGIN_FAILED" not in owner_actions and "LOGIN_FAILED" in admin_actions


# ---------------------------------------------------------------- AI
# TC-AIG-01 (SRS 11.3)
def test_ai_calls_are_logged_with_phone_masked(client, staff_h, owner_h, fake_ai):
    fake_ai.response = '{"answer": "Gợi ý", "suggestions": []}'
    r = client.post("/api/ai/advisor", json={"message": "khách 0912345678 cần tai nghe"}, headers=staff_h)
    assert r.status_code == 200
    logs = client.get("/api/ai/logs", headers=owner_h).json()
    assert logs["total"] == 1
    item = logs["items"][0]
    assert item["feature"] == "advisor" and item["prompt_version"] == "v3" and item["status"] == "success"
    assert "0912345678" not in item["question"] and "[SĐT]" in item["question"]  # TC-AIG-01


def test_staff_only_sees_own_ai_logs(client, staff_h, owner_h):
    client.post("/api/ai/advisor", json={"message": "tai nghe"}, headers=staff_h)
    client.post("/api/ai/advisor", json={"message": "sạc"}, headers=owner_h)
    assert client.get("/api/ai/logs", headers=staff_h).json()["total"] == 1
    assert client.get("/api/ai/logs", headers=owner_h).json()["total"] == 2


# FR-AIG-08
def test_ai_can_be_switched_off(client, admin_h, staff_h):
    client.put("/api/settings", json={"values": {"ai_enabled": False}}, headers=admin_h)
    r = client.post("/api/ai/advisor", json={"message": "tai nghe"}, headers=staff_h)
    assert r.status_code == 503
    assert client.get("/api/ai/status", headers=staff_h).json()["switched_on"] is False
    assert client.get("/api/products", headers=staff_h).status_code == 200  # NFR-REL-05: phần khác vẫn chạy


# TC-AIG-05 (SRS 11.3)
def test_ai_rate_limit_per_hour(client, admin_h, staff_h):
    client.put("/api/settings", json={"values": {"ai_rate_limit_per_hour": 2}}, headers=admin_h)
    for _ in range(2):
        assert client.post("/api/ai/advisor", json={"message": "tai nghe"}, headers=staff_h).status_code == 200
    assert client.post("/api/ai/advisor", json={"message": "tai nghe"}, headers=staff_h).status_code == 429


# FR-AIG-01, FR-AIG-08
def test_prompt_version_comes_from_settings(client, admin_h, staff_h, owner_h):
    client.put("/api/settings", json={"values": {"ai_prompt_version": "v1"}}, headers=admin_h)
    assert client.post("/api/ai/advisor", json={"message": "tai nghe"}, headers=staff_h).json()["version"] == "v1"


# ---------------------------------------------------------------- Sao lưu
def test_backup_and_restore_roundtrip(client, admin_h, owner_h):
    r = client.post("/api/admin/backup", headers=admin_h)
    assert r.status_code == 200 and r.content.startswith(b"SQLite format 3\x00")
    snapshot = r.content
    client.post("/api/categories", json={"name": "Nhóm tạm"}, headers=owner_h)
    assert any(c["name"] == "Nhóm tạm" for c in client.get("/api/categories", headers=owner_h).json())
    r = client.post("/api/admin/restore", files={"file": ("b.db", snapshot, "application/octet-stream")},
                    headers=admin_h)
    assert r.status_code == 200, r.text
    assert not any(c["name"] == "Nhóm tạm" for c in client.get("/api/categories", headers=owner_h).json())


def test_restore_rejects_invalid_file_and_non_admin(client, admin_h, owner_h):
    bad = client.post("/api/admin/restore", files={"file": ("x.db", b"not a database", "application/octet-stream")},
                      headers=admin_h)
    assert bad.status_code == 400
    assert client.post("/api/admin/backup", headers=owner_h).status_code == 403
