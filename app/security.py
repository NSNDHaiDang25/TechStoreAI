import hashlib
import hmac
import re
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Query, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Branch, RevokedToken, User, now
from app.services import branch_scope

ALGORITHM = "HS256"
BCRYPT_ROUNDS = 12  # mỗi lần băm ~0,2 giây: đủ chậm để chống dò mật khẩu, đăng nhập vẫn nhanh
_PBKDF2_ROUNDS = 200_000  # chỉ để kiểm tra mật khẩu băm theo cách cũ (trước khi dùng bcrypt)
bearer = HTTPBearer(auto_error=False)


def _password_bytes(password: str) -> bytes:
    # bcrypt chỉ dùng 72 byte đầu (bcrypt 5 báo lỗi nếu dài hơn), cắt sẵn để lúc băm và lúc kiểm tra giống nhau
    return password.encode()[:72]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_password_bytes(password), bcrypt.gensalt(BCRYPT_ROUNDS)).decode()


def verify_password(password: str, stored: str) -> bool:
    if stored.startswith("pbkdf2$"):
        return _verify_pbkdf2(password, stored)
    try:
        return bcrypt.checkpw(_password_bytes(password), stored.encode())
    except ValueError:  # chuỗi băm hỏng
        return False


def needs_rehash(stored: str) -> bool:
    """Mật khẩu còn băm theo cách cũ: băm lại bằng bcrypt ở lần đăng nhập thành công kế tiếp."""
    return stored.startswith("pbkdf2$")


def _verify_pbkdf2(password: str, stored: str) -> bool:
    try:
        _, salt, digest = stored.split("$")
    except ValueError:
        return False
    check = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _PBKDF2_ROUNDS).hex()
    return hmac.compare_digest(check, digest)


PASSWORD_RULE = "Mật khẩu chưa đủ mạnh: tối thiểu 8 ký tự, có cả chữ và số"


def check_password_strength(password: str) -> str:
    """BR-46 / FR-AUT-07: tối thiểu 8 ký tự gồm chữ và số."""
    if len(password) < 8 or not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise ValueError(PASSWORD_RULE)
    return password


def create_token(user: User, hours: int | None = None) -> str:
    expire = datetime.now(timezone.utc) + (timedelta(hours=hours) if hours
                                           else timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    payload = {"sub": str(user.id), "role": user.role, "exp": expire, "jti": uuid.uuid4().hex}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])


def revoke_token(db: Session, payload: dict) -> None:
    """FR-AUT-05: lưu jti của token vào revoked_tokens; token đó bị từ chối ở mọi endpoint."""
    jti = payload.get("jti")
    if not jti or db.get(RevokedToken, jti):
        return
    exp = datetime.fromtimestamp(payload["exp"], timezone.utc).astimezone(timezone(timedelta(hours=7)))
    db.add(RevokedToken(jti=jti, user_id=int(payload["sub"]), expires_at=exp.replace(tzinfo=None)))
    # Dọn token đã hết hạn để bảng không phình mãi
    db.query(RevokedToken).filter(RevokedToken.expires_at < now()).delete()


NO_BRANCH = "Tài khoản chưa được gán chi nhánh. Liên hệ quản trị viên"


def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    unauthorized = HTTPException(status.HTTP_401_UNAUTHORIZED, "Chưa đăng nhập hoặc phiên đã hết hạn")
    if creds is None:
        raise unauthorized
    try:
        payload = decode_token(creds.credentials)
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise unauthorized
    if payload.get("jti") and db.get(RevokedToken, payload["jti"]):
        raise unauthorized
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise unauthorized
    if user.role != "admin":  # mỗi chi nhánh độc lập: chỉ đọc / ghi dữ liệu chi nhánh của mình
        if user.branch_id is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, NO_BRANCH)
        branch_scope.set_scope(db, user.branch_id)
    request.state.token_payload = payload
    return user


def require_roles(*roles: str):
    """Dependency kiểm tra vai trò. Ba vai trò độc lập, không kế thừa quyền của nhau (SRS bảng 4.2):
    quản trị viên không bán hàng, không xem giá vốn và doanh thu, chỉ gọi được API ghi rõ "admin"."""
    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Bạn không có quyền thực hiện chức năng này")
        return user
    return checker


# Nhóm quyền dùng chung
ALL_STAFF = require_roles("owner", "staff")
MANAGERS = require_roles("owner")
ADMIN_ONLY = require_roles("admin")
ADMIN_OR_OWNER = require_roles("admin", "owner")
ANY_ROLE = require_roles("admin", "owner", "staff")


def branch_view(base):
    """Thêm tham số ?branch= cho API xem số liệu: trống = chi nhánh của mình; "all" = mọi chi nhánh;
    số = một chi nhánh. Chỉ chủ cửa hàng của chi nhánh chính được xem ngoài chi nhánh mình (chỉ đọc)."""
    def checker(branch: str | None = Query(None, description="all | id chi nhánh (chỉ chi nhánh chính)"),
                user: User = Depends(base), db: Session = Depends(get_db)) -> User:
        if branch in (None, "", "own") or branch == str(user.branch_id):
            return user
        if user.role != "owner" or not user.branch_is_main:
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                "Chỉ chủ cửa hàng của chi nhánh chính được xem số liệu các chi nhánh khác")
        if branch == "all":
            branch_scope.view_branches(db, None)
            return user
        if not branch.isdigit() or db.get(Branch, int(branch)) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy chi nhánh")
        branch_scope.view_branches(db, int(branch))
        return user
    return checker


CATALOG_MAIN_ONLY = "Sản phẩm, nhóm hàng và nhà cung cấp dùng chung cho mọi chi nhánh, chỉ chi nhánh chính được thêm, sửa, xóa"


def _catalog_editor(user: User = Depends(MANAGERS)) -> User:
    """Sản phẩm, nhóm hàng, nhà cung cấp dùng chung: chỉ chủ cửa hàng chi nhánh chính thêm / sửa / xóa."""
    if not user.branch_is_main:
        raise HTTPException(status.HTTP_403_FORBIDDEN, CATALOG_MAIN_ONLY)
    return user


CATALOG_EDITORS = _catalog_editor

# Xem số liệu kèm ?branch= (chi nhánh chính tổng hợp mọi chi nhánh)
MANAGERS_VIEW = branch_view(MANAGERS)
ALL_STAFF_VIEW = branch_view(ALL_STAFF)
