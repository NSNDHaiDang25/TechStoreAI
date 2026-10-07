"""Test tự tạo tài khoản ở màn hình đăng nhập: chờ quản trị viên duyệt rồi mới đăng nhập được."""
import pytest

from app.config import settings
from app.routers import auth
from app.services.mailer import MailError


def register(client, username="nguyenvanan", full_name="Nguyễn Văn An", password="matkhau123", **extra):
    return client.post("/api/auth/register", json={"username": username, "full_name": full_name, "password": password, **extra})


def login(client, username, password):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def user_named(client, admin_h, username):
    return next(u for u in client.get("/api/users", headers=admin_h).json() if u["username"] == username)


def test_register_waits_for_admin_approval(client, admin_h):
    r = register(client)
    assert r.status_code == 201, r.text
    r = login(client, "nguyenvanan", "matkhau123")
    assert r.status_code == 403
    assert "chờ quản trị viên duyệt" in r.json()["detail"]

    u = user_named(client, admin_h, "nguyenvanan")
    assert u["pending"] is True and u["is_active"] is False and u["role"] == "staff"
    r = client.put(f"/api/users/{u['id']}", json={"is_active": True}, headers=admin_h)
    assert r.status_code == 200 and r.json()["pending"] is False

    r = login(client, "nguyenvanan", "matkhau123")
    assert r.status_code == 200, r.text
    assert r.json()["user"]["role"] == "staff"


def test_register_cannot_choose_role(client, admin_h):
    assert register(client, role="admin").status_code == 201
    assert user_named(client, admin_h, "nguyenvanan")["role"] == "staff"


def test_register_rejects_taken_username_ignoring_case(client):
    r = register(client, username="STAFF")
    assert r.status_code == 400
    assert r.json()["detail"] == "Tên đăng nhập đã được sử dụng"


@pytest.mark.parametrize("field, value", [
    ("username", "nguyễn văn"),  # có dấu, có khoảng trắng
    ("username", "ab"),
    ("password", "12345"),
    ("full_name", "   "),
])
def test_register_validates_input(client, field, value):
    assert register(client, **{field: value}).status_code == 422


def test_admin_rejects_only_pending_accounts(client, admin_h, owner_h):
    register(client)
    pending = user_named(client, admin_h, "nguyenvanan")
    staff = user_named(client, admin_h, "staff")
    assert client.delete(f"/api/users/{pending['id']}", headers=owner_h).status_code == 403
    assert client.delete(f"/api/users/{staff['id']}", headers=admin_h).status_code == 400  # đã dùng: chỉ khóa, không xóa
    r = client.delete(f"/api/users/{pending['id']}", headers=admin_h)
    assert r.status_code == 200, r.text
    assert all(u["username"] != "nguyenvanan" for u in client.get("/api/users", headers=admin_h).json())
    assert register(client).status_code == 201  # tên đăng nhập được dùng lại sau khi từ chối


def test_too_many_pending_accounts(client, monkeypatch):
    monkeypatch.setattr(auth, "REGISTER_MAX_PENDING", 1)
    assert register(client, username="nguoi1").status_code == 201
    assert register(client, username="nguoi2").status_code == 429


def test_admin_gets_email_and_mail_failure_does_not_block(client, monkeypatch):
    sent = []
    monkeypatch.setattr(settings, "ADMIN_EMAIL", "boss@example.com")
    monkeypatch.setattr(auth, "mail_configured", lambda: True)
    monkeypatch.setattr(auth, "send_mail", lambda to, subject, text: sent.append((to, subject)))
    assert register(client).status_code == 201
    assert sent and sent[0][0] == "boss@example.com" and "nguyenvanan" in sent[0][1]

    def broken(*_):
        raise MailError("SMTP lỗi")
    monkeypatch.setattr(auth, "send_mail", broken)
    assert register(client, username="nguoi2").status_code == 201
