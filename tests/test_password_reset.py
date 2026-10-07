"""Test quên mật khẩu: quản trị viên nhận mã qua email (gửi mail giả) rồi đặt mật khẩu mới."""
import re
from datetime import datetime, timedelta

import pytest

from app.config import settings
from app.models import PasswordReset
from app.routers import auth
from app.services.mailer import MailError


@pytest.fixture
def outbox(monkeypatch):
    sent = []
    monkeypatch.setattr(settings, "ADMIN_EMAIL", "boss@example.com")
    monkeypatch.setattr(auth, "mail_configured", lambda: True)
    monkeypatch.setattr(auth, "send_mail", lambda to, subject, text: sent.append({"to": to, "subject": subject, "text": text}))
    return sent


def code_of(mail):
    return re.search(r"Mã xác nhận: (\d{6})", mail["text"]).group(1)


def forgot(client, username="admin"):
    return client.post("/api/auth/forgot-password", json={"username": username})


def reset(client, code, password="moi123456", username="admin"):
    return client.post("/api/auth/reset-password", json={"username": username, "code": code, "new_password": password})


def can_login(client, username, password):
    return client.post("/api/auth/login", json={"username": username, "password": password}).status_code == 200


# TC-AUT-04 (SRS 11.3)
def test_admin_resets_password_with_emailed_code(client, outbox):
    r = forgot(client)
    assert r.status_code == 200, r.text
    assert "b***@example.com" in r.json()["message"]
    assert len(outbox) == 1 and outbox[0]["to"] == "boss@example.com"
    code = code_of(outbox[0])
    assert code in outbox[0]["subject"]

    assert reset(client, code).status_code == 200
    assert can_login(client, "admin", "moi123456")
    assert not can_login(client, "admin", "admin123")
    assert reset(client, code, "khac123456").status_code == 400  # mã chỉ dùng một lần


def test_non_admin_gets_same_message_but_no_email(client, outbox):
    admin_msg = forgot(client).json()["message"]
    for username in ("owner", "khong-ton-tai"):
        r = forgot(client, username)
        assert r.status_code == 200
        assert r.json()["message"] == admin_msg
    assert len(outbox) == 1
    assert reset(client, "000000", username="owner").status_code == 400
    assert can_login(client, "owner", "owner123")


def test_wrong_code_is_limited(client, outbox):
    forgot(client)
    code = code_of(outbox[0])
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(auth.RESET_MAX_ATTEMPTS - 1):
        assert "còn" in reset(client, wrong).json()["detail"]
    assert "quá nhiều lần" in reset(client, wrong).json()["detail"]
    assert reset(client, code).status_code == 400  # đúng mã nhưng đã bị hủy
    assert can_login(client, "admin", "admin123")


def test_expired_code_rejected(client, db, outbox):
    forgot(client)
    db.query(PasswordReset).update({"expires_at": datetime(2000, 1, 1)})
    db.commit()
    assert reset(client, code_of(outbox[0])).status_code == 400


def test_resend_waits_and_new_code_replaces_old(client, db, outbox):
    forgot(client)
    forgot(client)  # chưa đủ 60 giây: không gửi thêm
    assert len(outbox) == 1
    db.query(PasswordReset).update({"created_at": datetime.now() - timedelta(minutes=2)})
    db.commit()
    forgot(client)
    assert len(outbox) == 2
    old, new = code_of(outbox[0]), code_of(outbox[1])
    if old != new:
        assert reset(client, old).status_code == 400
    assert reset(client, new).status_code == 200


def test_mail_failure_reports_error_and_keeps_no_code(client, monkeypatch, outbox):
    def broken(*_):
        raise MailError("Gmail từ chối đăng nhập")
    monkeypatch.setattr(auth, "send_mail", broken)
    r = forgot(client)
    assert r.status_code == 502
    assert "Gmail từ chối đăng nhập" in r.json()["detail"]
    monkeypatch.setattr(auth, "send_mail", lambda to, subject, text: outbox.append({"text": text, "subject": subject}))
    assert forgot(client).status_code == 200  # lần lỗi không tính vào thời gian chờ
    assert len(outbox) == 1


def test_not_configured(client, monkeypatch):
    monkeypatch.setattr(auth, "mail_configured", lambda: False)
    assert forgot(client).status_code == 503
