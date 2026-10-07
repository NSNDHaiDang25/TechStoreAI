"""Tham số cấu hình lưu trong bảng settings (SRS bảng 2.5, FR-SYS-02).

Đọc lại từ CSDL mỗi lần dùng nên sửa xong có hiệu lực ngay, không cần khởi động lại.
Chưa có dòng trong bảng thì dùng giá trị mặc định dưới đây (một số lấy từ .env để giữ cấu hình cũ).
"""
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings as env
from app.models import Setting, User, now


@dataclass(frozen=True)
class Spec:
    default: Any
    kind: type  # int | float | bool | str
    editor: str  # owner = tham số kinh doanh, admin = tham số kỹ thuật
    description: str
    min: float | None = None
    max: float | None = None


SPECS: dict[str, Spec] = {
    # ---- tham số kinh doanh (chủ cửa hàng sửa)
    "low_stock_threshold": Spec(5, int, "owner", "Tồn kho nhỏ hơn giá trị này thì cảnh báo sắp hết hàng", 0, 10_000),
    "return_window_hours": Spec(24, int, "owner", "Hạn đổi trả tính từ lúc thanh toán (giờ)", 0, 24 * 30),
    "warranty_months_default": Spec(12, int, "owner", "Bảo hành mặc định khi nhóm hàng không đặt riêng (tháng)", 0, 120),
    "vat_rate_default": Spec(10, int, "owner", "VAT mặc định (%) cho nhóm hàng mới", 0, 100),
    "points_per_vnd": Spec(10_000, int, "owner", "Số đồng thanh toán để được 1 điểm", 1, 100_000_000),
    "point_value_vnd": Spec(100, int, "owner", "Giá trị quy đổi của 1 điểm khi dùng (đồng)", 0, 1_000_000),
    "points_max_percent": Spec(50, int, "owner", "Tỷ lệ tối đa của hóa đơn được trả bằng điểm (%)", 0, 100),
    "tier_silver_min": Spec(20_000_000, int, "owner", "Tổng chi tiêu để lên hạng Bạc", 0, 2_000_000_000),
    "tier_gold_min": Spec(50_000_000, int, "owner", "Tổng chi tiêu để lên hạng Vàng", 0, 2_000_000_000),
    "pending_payment_minutes": Spec(30, int, "owner", "Thời gian giữ hóa đơn chờ chuyển khoản (phút)", 1, 24 * 60),
    "store_name": Spec(env.SHOP_NAME, str, "owner", "Tên cửa hàng in trên hóa đơn"),
    "store_tax_code": Spec("", str, "owner", "Mã số thuế in trên hóa đơn"),
    "store_address": Spec("", str, "owner", "Địa chỉ in trên hóa đơn"),
    "store_phone": Spec("", str, "owner", "Số điện thoại in trên hóa đơn"),
    "bank_bin": Spec(env.VIETQR_BANK_BIN, str, "owner", "Mã BIN ngân hàng nhận tiền (VietQR)"),
    "bank_name": Spec(env.VIETQR_BANK_NAME, str, "owner", "Tên ngân hàng nhận tiền"),
    "bank_account": Spec(env.VIETQR_ACCOUNT_NO, str, "owner", "Số tài khoản nhận tiền"),
    "bank_account_name": Spec(env.VIETQR_ACCOUNT_NAME, str, "owner", "Tên chủ tài khoản nhận tiền"),
    # ---- tham số kỹ thuật (quản trị viên sửa)
    "jwt_expire_hours": Spec(max(1, env.ACCESS_TOKEN_EXPIRE_MINUTES // 60), int, "admin", "Thời hạn token truy cập (giờ)", 1, 72),
    "login_max_fail": Spec(5, int, "admin", "Số lần đăng nhập sai liên tiếp trước khi khóa tạm", 1, 100),
    "login_lock_minutes": Spec(15, int, "admin", "Thời gian khóa tạm sau khi sai quá số lần (phút)", 1, 24 * 60),
    "face_login_enabled": Spec(True, bool, "admin", "Cho phép chủ cửa hàng và quản trị viên đăng nhập bằng Face ID"),
    "face_liveness_enabled": Spec(True, bool, "admin",
                                  "Face ID kiểm tra người thật: yêu cầu quay đầu trái, phải theo thứ tự ngẫu nhiên"),
    "face_login_threshold": Spec(0.40, float, "admin",
                                 "Độ giống tối thiểu để Face ID chấp nhận (0.36 - 0.9, càng cao càng chặt)", 0.36, 0.9),
    "ai_enabled": Spec(True, bool, "admin", "Bật hoặc tắt toàn bộ tính năng AI"),
    "ai_model_name": Spec(env.GEMINI_MODEL, str, "admin", "Tên mô hình Gemini"),
    "ai_timeout_seconds": Spec(int(env.AI_TIMEOUT_SECONDS), int, "admin", "Timeout mỗi lần gọi AI (giây)", 1, 300),
    "ai_max_retries": Spec(env.AI_MAX_RETRIES, int, "admin", "Số lần thử lại khi gọi AI lỗi", 0, 10),
    "ai_rate_limit_per_hour": Spec(20, int, "admin", "Số lượt gọi AI tối đa mỗi người mỗi giờ (0 = không giới hạn)", 0, 10_000),
    "ai_prompt_version": Spec(env.ADVISOR_PROMPT_VERSION, str, "admin", "Phiên bản prompt tư vấn đang dùng (v1, v2, v3)"),
}


def _parse(spec: Spec, raw: str) -> Any:
    if spec.kind is bool:
        return str(raw).strip().lower() in ("1", "true", "yes", "on")
    return spec.kind(raw)


def _to_str(spec: Spec, value: Any) -> str:
    if spec.kind is bool:
        return "true" if value else "false"
    return str(value)


def get(db: Session, key: str) -> Any:
    spec = SPECS[key]
    row = db.get(Setting, key)
    if row is None:
        return spec.default
    try:
        return _parse(spec, row.value)
    except (TypeError, ValueError):
        return spec.default


def get_many(db: Session, keys: list[str] | None = None) -> dict[str, Any]:
    keys = keys or list(SPECS)
    rows = {r.key: r for r in db.scalars(select(Setting).where(Setting.key.in_(keys)))}
    out = {}
    for k in keys:
        spec = SPECS[k]
        try:
            out[k] = _parse(spec, rows[k].value) if k in rows else spec.default
        except (TypeError, ValueError):
            out[k] = spec.default
    return out


def editable_by(user: User) -> set[str]:
    if user.role == "admin":
        return {k for k, s in SPECS.items() if s.editor == "admin"}
    if user.role == "owner":
        return {k for k, s in SPECS.items() if s.editor == "owner"}
    return set()


def describe(db: Session, user: User) -> list[dict]:
    values = get_many(db)
    allowed = editable_by(user)
    return [{"key": k, "value": values[k], "default": s.default, "type": s.kind.__name__, "editor": s.editor,
             "description": s.description, "editable": k in allowed, "min": s.min, "max": s.max}
            for k, s in SPECS.items() if s.editor == user.role or user.role == "admin" or k in allowed]


def validate(key: str, value: Any) -> Any:
    if key not in SPECS:
        raise ValueError(f"Tham số '{key}' không tồn tại")
    spec = SPECS[key]
    try:
        parsed = _parse(spec, value) if not isinstance(value, spec.kind) or spec.kind is bool else value
    except (TypeError, ValueError):
        raise ValueError(f"Giá trị của '{key}' không hợp lệ")
    if spec.kind in (int, float):
        if spec.min is not None and parsed < spec.min or spec.max is not None and parsed > spec.max:
            raise ValueError(f"'{key}' phải trong khoảng {spec.min:g} đến {spec.max:g}")
    if spec.kind is str and len(str(parsed)) > 255:
        raise ValueError(f"'{key}' dài quá 255 ký tự")
    if key == "ai_prompt_version" and parsed not in ("v1", "v2", "v3"):
        raise ValueError("Phiên bản prompt phải là v1, v2 hoặc v3")
    return parsed


def update(db: Session, user: User, changes: dict[str, Any]) -> dict[str, tuple[Any, Any]]:
    """Ghi các tham số được phép. Trả về {key: (giá trị cũ, giá trị mới)} để ghi audit log."""
    allowed = editable_by(user)
    denied = [k for k in changes if k not in allowed]
    if denied:
        raise PermissionError(f"Bạn không được sửa tham số: {', '.join(sorted(denied))}")
    diff = {}
    for key, raw in changes.items():
        new = validate(key, raw)
        old = get(db, key)
        if old == new:
            continue
        row = db.get(Setting, key)
        if row is None:
            row = Setting(key=key, description=SPECS[key].description)
            db.add(row)
        row.value = _to_str(SPECS[key], new)
        row.updated_by = user.id
        row.updated_at = now()
        diff[key] = (old, new)
    db.flush()  # session tắt autoflush: ghi xuống để các truy vấn sau đọc được giá trị mới
    if "tier_silver_min" in changes or "tier_gold_min" in changes:
        values = get_many(db, ["tier_silver_min", "tier_gold_min"])
        if values["tier_silver_min"] >= values["tier_gold_min"]:
            raise ValueError("Ngưỡng hạng Bạc phải nhỏ hơn ngưỡng hạng Vàng")
    return diff
