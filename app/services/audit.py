"""Ghi nhật ký thao tác nhạy cảm (FR-SYS-03): đăng nhập thất bại, đổi giá, hủy hóa đơn, đổi trả,
điều chỉnh tồn, điều chỉnh điểm, đổi vai trò, sửa cấu hình...

Hàm không commit: bản ghi nằm chung giao dịch với nghiệp vụ, nghiệp vụ lỗi thì nhật ký cũng không ghi.
"""
import json
from contextvars import ContextVar
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog, User

# Địa chỉ IP của request hiện tại, middleware trong app.main gán vào
client_ip: ContextVar[str | None] = ContextVar("client_ip", default=None)

# Hành động nghiệp vụ chủ cửa hàng được xem; các hành động còn lại là log kỹ thuật chỉ quản trị viên xem (bảng 4.2)
BUSINESS_ACTIONS = {
    "PRICE_CHANGE", "INVOICE_CANCEL", "INVOICE_CANCEL_REQUEST", "INVOICE_CANCEL_REJECT", "INVOICE_REPRINT",
    "INVOICE_BELOW_COST", "RETURN_CREATE", "STOCK_ADJUST", "POINTS_ADJUST", "PURCHASE_CONFIRM",
    "PURCHASE_CANCEL", "SETTINGS_UPDATE_OWNER", "PRODUCT_IMPORT", "CUSTOMER_DEACTIVATE", "PROMOTION_UPDATE", "TIER_UPDATE",
}


def _dump(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


def log(db: Session, user: User | None, action: str, entity: str, entity_id: int | None = None,
        old: Any = None, new: Any = None) -> None:
    db.add(AuditLog(user_id=user.id if user else None, action=action, entity=entity, entity_id=entity_id,
                    old_value=_dump(old), new_value=_dump(new), ip_address=client_ip.get()))
