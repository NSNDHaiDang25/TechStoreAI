"""Hiển thị nhật ký thao tác (UC-06): lọc, tên tiếng Việt của thao tác / đối tượng, tên dễ đọc của bản ghi bị tác động
("Trên"), danh sách thay đổi trước -> sau. Dùng chung cho trang Nhật ký và tệp Excel xuất ra."""
import json
from datetime import datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import (AuditLog, Branch, Customer, CustomerTier, ImportReceipt, Invoice, Product, ProductSerial,
                        Promotion, Return, User)
from app.services import app_settings, audit

# Trùng chữ với giao diện (frontend dịch sang tiếng Anh theo đúng chuỗi này)
ACTION_LABELS = {
    "LOGIN_FAILED": "Đăng nhập sai", "FACE_LOGIN": "Đăng nhập Face ID", "FACE_ENROLL": "Đăng ký Face ID",
    "FACE_DELETE": "Xóa Face ID", "ACCOUNT_LOCKED": "Khóa tài khoản tạm", "USER_CREATE": "Tạo tài khoản",
    "USER_UPDATE": "Sửa tài khoản", "ROLE_CHANGE": "Đổi vai trò", "PASSWORD_RESET": "Đặt lại mật khẩu",
    "PASSWORD_CHANGE": "Đổi mật khẩu", "SETTINGS_UPDATE": "Sửa cấu hình", "SETTINGS_UPDATE_OWNER": "Sửa cấu hình kinh doanh",
    "DB_BACKUP": "Sao lưu CSDL", "DB_RESTORE": "Khôi phục CSDL", "INVOICE_CANCEL": "Hủy hóa đơn",
    "INVOICE_CANCEL_REQUEST": "Yêu cầu hủy hóa đơn", "INVOICE_CANCEL_REJECT": "Từ chối hủy hóa đơn",
    "INVOICE_REPRINT": "In lại hóa đơn", "INVOICE_BELOW_COST": "Bán dưới giá vốn", "PRICE_CHANGE": "Đổi giá",
    "STOCK_ADJUST": "Điều chỉnh tồn", "SERIAL_UPDATE": "Sửa serial", "PURCHASE_CONFIRM": "Xác nhận nhập kho",
    "PURCHASE_CANCEL": "Hủy phiếu nhập", "RETURN_CREATE": "Đổi trả", "POINTS_ADJUST": "Điều chỉnh điểm",
    "TIER_UPDATE": "Sửa hạng khách", "PROMOTION_UPDATE": "Sửa khuyến mãi", "CUSTOMER_DEACTIVATE": "Ngừng theo dõi khách",
    "CUSTOMER_ACTIVATE": "Theo dõi lại khách", "PRODUCT_IMPORT": "Nhập sản phẩm từ tệp",
    "BRANCH_CREATE": "Thêm chi nhánh", "BRANCH_UPDATE": "Sửa chi nhánh", "USER_DELETE": "Xóa tài khoản",
}
ENTITY_LABELS = {
    "users": "Tài khoản", "products": "Sản phẩm", "product_serials": "Serial", "customers": "Khách hàng",
    "customer_tiers": "Hạng khách", "invoices": "Hóa đơn", "returns": "Đổi trả", "import_receipts": "Phiếu nhập",
    "promotions": "Khuyến mãi", "settings": "Cấu hình", "database": "Cơ sở dữ liệu", "branches": "Chi nhánh",
}
FIELD_LABELS = {
    "sale_price": "Giá bán", "cost_price": "Giá vốn", "full_name": "Họ tên", "username": "Tên đăng nhập",
    "role": "Vai trò", "is_active": "Trạng thái", "email": "Email", "phone": "Số điện thoại", "branch": "Chi nhánh",
    "points": "Điểm", "reason": "Lý do", "status": "Trạng thái", "name": "Tên", "address": "Địa chỉ",
    "failed_login_count": "Số lần sai", "locked_until": "Khóa đến", "method": "Cách đăng nhập", "score": "Độ khớp",
    "liveness": "Kiểm tra người thật", "samples": "Số ảnh mẫu", "file": "Tệp", "created": "Đã tạo", "skipped": "Bỏ qua",
    "code": "Mã", "total": "Tổng tiền", "invoice": "Hóa đơn", "refund": "Hoàn tiền", "type": "Loại",
    "print_count": "Số lần in", "bytes": "Dung lượng", "stock": "Tồn kho", "quantity": "Số lượng",
    "serial_no": "Số serial", "value": "Giá trị", "kept_history": "Giữ lịch sử",
}
ROLE_LABELS = {"admin": "Quản trị viên", "owner": "Chủ cửa hàng", "staff": "Nhân viên bán hàng"}
TARGETS = {  # entity -> (model, tên hiển thị)
    "users": (User, lambda x: f"{x.username} · {x.full_name}"),
    "products": (Product, lambda x: f"{x.code} · {x.name}"),
    "customers": (Customer, lambda x: f"{x.code} · {x.name}"),
    "invoices": (Invoice, lambda x: x.code),
    "returns": (Return, lambda x: x.code),
    "import_receipts": (ImportReceipt, lambda x: x.code + (f" · {x.supplier}" if x.supplier else "")),
    "promotions": (Promotion, lambda x: x.name),
    "customer_tiers": (CustomerTier, lambda x: x.name),
    "product_serials": (ProductSerial, lambda x: x.serial_no),
    "branches": (Branch, lambda x: x.name),
}
# Tìm kiếm theo tên / mã của bản ghi bị tác động
SEARCHABLE = {
    "users": (User, (User.username, User.full_name)),
    "products": (Product, (Product.code, Product.name)),
    "customers": (Customer, (Customer.code, Customer.name)),
    "invoices": (Invoice, (Invoice.code,)),
    "import_receipts": (ImportReceipt, (ImportReceipt.code,)),
}


def scoped(user: User):
    """Phạm vi được xem: chủ cửa hàng chỉ thấy nhật ký nghiệp vụ của chi nhánh mình (chưa gán chi nhánh: mọi chi nhánh)."""
    stmt = select(AuditLog)
    if user.role == "owner":
        stmt = stmt.where(AuditLog.action.in_(audit.BUSINESS_ACTIONS))
        if user.branch_id:
            stmt = stmt.where(AuditLog.branch_id == user.branch_id)
    return stmt


def filtered(user: User, *, action=None, entity=None, user_id=None, date_from=None, date_to=None, q=None,
             branch_id=None):
    from app.services.reports import parse_range
    stmt = scoped(user)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if entity:
        stmt = stmt.where(AuditLog.entity == entity)
    if user_id == 0:
        stmt = stmt.where(AuditLog.user_id.is_(None))  # thao tác của hệ thống / người chưa đăng nhập
    elif user_id:
        stmt = stmt.where(AuditLog.user_id == user_id)
    if date_from or date_to:
        start, end = parse_range(date_from, date_to)
        stmt = stmt.where(AuditLog.created_at >= start, AuditLog.created_at < end)
    if q and q.strip():
        like = f"%{q.strip()}%"
        conds = [AuditLog.old_value.ilike(like), AuditLog.new_value.ilike(like),
                 AuditLog.user_id.in_(select(User.id).where(or_(User.full_name.ilike(like), User.username.ilike(like))))]
        for name, (model, cols) in SEARCHABLE.items():
            conds.append((AuditLog.entity == name) & AuditLog.entity_id.in_(
                select(model.id).where(or_(*[c.ilike(like) for c in cols]))))
        stmt = stmt.where(or_(*conds))
    if user.role == "admin" and branch_id is not None:
        stmt = stmt.where(AuditLog.branch_id.is_(None) if branch_id == 0 else AuditLog.branch_id == branch_id)
    return stmt


def branch_counts(db: Session, stmt) -> dict:
    """Số dòng theo chi nhánh (cho các tab), tính trên cùng bộ lọc trừ chi nhánh. Khóa 0 = không thuộc chi nhánh."""
    sub = stmt.subquery()
    rows = db.execute(select(sub.c.branch_id, func.count()).group_by(sub.c.branch_id)).all()
    return {str(b or 0): n for b, n in rows}


def _load(value: str | None) -> Any:
    if value is None:
        return None
    try:
        return json.loads(value)
    except ValueError:
        return value


def _value(field: str | None, v: Any) -> Any:
    """Giá trị dễ đọc: vai trò, trạng thái hoạt động; số, chữ giữ nguyên để giao diện tự định dạng."""
    if field == "role" and v in ROLE_LABELS:
        return ROLE_LABELS[v]
    if field == "is_active" and isinstance(v, bool):
        return "Hoạt động" if v else "Đã khóa"
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False)[:200]
    return v


def _label(field: str) -> str:
    if field in FIELD_LABELS:
        return FIELD_LABELS[field]
    spec = app_settings.SPECS.get(field)
    return spec.description if spec else field


def changes(old_raw: str | None, new_raw: str | None) -> list[dict]:
    """Danh sách thay đổi [{field, label, old, new}]: chỉ các trường khác nhau; ghi mới (không có bản cũ) thì old = None."""
    old, new = _load(old_raw), _load(new_raw)
    if isinstance(old, dict) or isinstance(new, dict):
        old, new = old if isinstance(old, dict) else {}, new if isinstance(new, dict) else {}
        out = []
        for k in list(new) + [k for k in old if k not in new]:
            if old.get(k) != new.get(k):
                out.append({"field": k, "label": _label(k), "old": _value(k, old.get(k)), "new": _value(k, new.get(k))})
        return out
    if old is None and new is None:
        return []
    return [{"field": None, "label": None, "old": _value(None, old), "new": _value(None, new)}]


def targets(db: Session, rows: list[AuditLog]) -> dict[int, str]:
    """Tên dễ đọc của bản ghi bị tác động cho từng dòng nhật ký (truy vấn gộp theo loại đối tượng)."""
    ids: dict[str, set[int]] = {}
    for r in rows:
        if r.entity in TARGETS and r.entity_id:
            ids.setdefault(r.entity, set()).add(r.entity_id)
    names: dict[tuple[str, int], str] = {}
    for entity, wanted in ids.items():
        model, fmt = TARGETS[entity]
        for obj in db.scalars(select(model).where(model.id.in_(wanted))):
            names[(entity, obj.id)] = fmt(obj)
    out = {}
    for r in rows:
        name = names.get((r.entity, r.entity_id))
        if name is None:
            new = _load(r.new_value)
            if isinstance(new, dict) and new.get("username"):
                name = str(new["username"])            # đăng nhập sai bằng tên không tồn tại
            elif isinstance(new, dict) and new.get("file"):
                name = str(new["file"])                # nhập sản phẩm từ tệp
            elif r.entity_id:
                name = f"#{r.entity_id}"               # bản ghi đã bị xóa
        out[r.id] = name
    return out


def item(r: AuditLog, target: str | None) -> dict:
    return {"id": r.id, "created_at": r.created_at, "user_id": r.user_id,
            "user_name": (r.user.full_name or r.user.username) if r.user else None,
            "action": r.action, "action_label": ACTION_LABELS.get(r.action, r.action),
            "entity": r.entity, "entity_label": ENTITY_LABELS.get(r.entity, r.entity), "entity_id": r.entity_id,
            "target": target, "changes": changes(r.old_value, r.new_value),
            "old_value": r.old_value, "new_value": r.new_value, "ip_address": r.ip_address,
            "branch_id": r.branch_id, "branch_name": r.branch.name if r.branch else None}


def _cell(v: Any) -> str:
    if v is None:
        return "-"
    if isinstance(v, bool):
        return "Có" if v else "Không"
    if isinstance(v, int):
        return f"{v:,}".replace(",", ".")
    return str(v)


def export_rows(items: list[dict]) -> list[list]:
    rows = []
    for i in items:
        before = "\n".join(f"{c['label'] + ': ' if c['label'] else ''}{_cell(c['old'])}" for c in i["changes"] if c["old"] is not None)
        after = "\n".join(f"{c['label'] + ': ' if c['label'] else ''}{_cell(c['new'])}" for c in i["changes"])
        when = i["created_at"].strftime("%d/%m/%Y %H:%M") if isinstance(i["created_at"], datetime) else str(i["created_at"])
        rows.append([when, i["branch_name"] or "Hệ thống", i["user_name"] or "Hệ thống", i["entity_label"],
                     i["action_label"], i["target"] or "", before, after, i["ip_address"] or ""])
    return rows
