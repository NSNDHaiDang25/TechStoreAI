"""Test băm mật khẩu: bcrypt (SRS 4.1), mật khẩu băm theo cách cũ (PBKDF2) vẫn đăng nhập được và được nâng cấp."""
import hashlib

from sqlalchemy import select

from app import security
from app.models import User
from app.security import hash_password, needs_rehash, verify_password


def login(client, username, password):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def legacy_hash(password, salt="ab" * 16):
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), security._PBKDF2_ROUNDS).hex()
    return f"pbkdf2${salt}${digest}"


# FR-AUT-02
def test_hash_password_uses_bcrypt():
    h = hash_password("owner123")
    assert h.startswith("$2b$")
    assert hash_password("owner123") != h  # mỗi lần băm có salt riêng
    assert verify_password("owner123", h)
    assert not verify_password("owner124", h)
    assert not needs_rehash(h)


def test_long_password_and_broken_hash():
    long_pw = "mật khẩu rất dài " * 10  # hơn 72 byte
    assert verify_password(long_pw, hash_password(long_pw))
    assert not verify_password("x", "không-phải-chuỗi-băm")


def test_legacy_pbkdf2_login_upgrades_to_bcrypt(client, db):
    user = db.scalar(select(User).where(User.username == "staff"))
    user.password_hash = legacy_hash("staff123")
    db.commit()
    assert login(client, "staff", "sai-mat-khau").status_code == 401
    assert login(client, "staff", "staff123").status_code == 200
    db.expire_all()
    upgraded = db.scalar(select(User).where(User.username == "staff")).password_hash
    assert upgraded.startswith("$2b$")
    assert login(client, "staff", "staff123").status_code == 200
