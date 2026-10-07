"""Test gửi email: chọn Resend / SMTP theo cấu hình, báo lỗi rõ ràng (không gửi thật)."""
import smtplib

import httpx
import pytest

from app.config import settings
from app.services import mailer


@pytest.fixture
def cfg(monkeypatch):
    def set_(**kw):
        values = {"RESEND_API_KEY": "", "SMTP_USER": "", "SMTP_PASSWORD": "", "MAIL_FROM": "", "SMTP_PORT": 587, **kw}
        for k, v in values.items():
            monkeypatch.setattr(settings, k, v)
    return set_


def test_not_configured(cfg):
    cfg()
    assert not mailer.mail_configured()
    with pytest.raises(mailer.MailError):
        mailer.send_mail("a@example.com", "s", "t")


def test_resend_request_and_error(cfg, monkeypatch):
    cfg(RESEND_API_KEY="re_test", SMTP_USER="x@gmail.com", SMTP_PASSWORD="p")  # có Resend thì ưu tiên Resend
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append({"url": url, "headers": headers, "json": json})
        return httpx.Response(200 if len(calls) == 1 else 403, json={"message": "You can only send testing emails"})
    monkeypatch.setattr(mailer.httpx, "post", fake_post)

    mailer.send_mail("boss@example.com", "Mã", "123456")
    assert calls[0]["url"] == mailer.RESEND_URL
    assert calls[0]["headers"]["Authorization"] == "Bearer re_test"
    assert calls[0]["json"]["to"] == ["boss@example.com"]
    assert "onboarding@resend.dev" in calls[0]["json"]["from"]
    with pytest.raises(mailer.MailError, match="403"):
        mailer.send_mail("boss@example.com", "Mã", "123456")


class FakeSMTP:
    instances = []

    def __init__(self, host, port, timeout):
        self.host, self.port, self.log = host, port, []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def starttls(self):
        self.log.append("starttls")

    def login(self, user, password):
        if password != "apppassword":
            raise smtplib.SMTPAuthenticationError(535, b"bad")
        self.log.append(("login", user))

    def send_message(self, msg):
        self.log.append(("send", msg["To"], msg["From"]))


def test_smtp_starttls_and_bad_password(cfg, monkeypatch):
    FakeSMTP.instances.clear()
    monkeypatch.setattr(mailer.smtplib, "SMTP", FakeSMTP)
    cfg(SMTP_USER="shop@gmail.com", SMTP_PASSWORD="apppassword")
    mailer.send_mail("boss@example.com", "Mã", "123456")
    log = FakeSMTP.instances[0].log
    assert log[0] == "starttls" and log[1] == ("login", "shop@gmail.com")
    assert log[2][1] == "boss@example.com" and "shop@gmail.com" in log[2][2]

    cfg(SMTP_USER="shop@gmail.com", SMTP_PASSWORD="sai")
    with pytest.raises(mailer.MailError, match="mật khẩu ứng dụng"):
        mailer.send_mail("boss@example.com", "Mã", "123456")
