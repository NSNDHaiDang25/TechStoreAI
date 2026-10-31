"""Hệ thống (SRS 5.17): tham số cấu hình, audit log, nhật ký email, sao lưu và khôi phục CSDL."""
import sqlite3
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AuditLog, Branch, EmailLog, User, now
from app.schemas import SettingsUpdateIn
from app.security import ADMIN_ONLY, ADMIN_OR_OWNER, get_current_user
from app.services import app_settings, audit, audit_view, loyalty
from app.services.export import MEDIA, to_xlsx

router = APIRouter(prefix="/api", tags=["system"])


# ---------------------------------------------------------------- Cấu hình (UC-07, UC-08)
@router.get("/settings")
def get_settings(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Chủ cửa hàng thấy tham số kinh doanh, quản trị viên thấy tất cả. Nhân viên chỉ đọc vài tham số cần khi bán hàng."""
    if user.role == "staff":
        keys = ["low_stock_threshold", "return_window_hours", "point_value_vnd", "points_max_percent",
                "points_per_vnd", "pending_payment_minutes", "store_name", "store_address", "store_phone",
                "store_tax_code", "bank_name", "bank_account", "bank_account_name"]
        return {"items": [{"key": k, "value": v, "editable": False} for k, v in app_settings.get_many(db, keys).items()]}
    return {"items": app_settings.describe(db, user)}


@router.put("/settings")
def put_settings(data: SettingsUpdateIn, db: Session = Depends(get_db), user: User = Depends(ADMIN_OR_OWNER)):
    try:
        diff = app_settings.update(db, user, data.values)
    except PermissionError as e:
        db.rollback()
        raise HTTPException(403, str(e))
    except ValueError as e:
        db.rollback()
        raise HTTPException(400, str(e))
    if {"tier_silver_min", "tier_gold_min"} & diff.keys():
        loyalty.sync_tiers_from_settings(db)
    if diff:
        action = "SETTINGS_UPDATE_OWNER" if user.role == "owner" else "SETTINGS_UPDATE"
        audit.log(db, user, action, "settings", None,
                  old={k: v[0] for k, v in diff.items()}, new={k: v[1] for k, v in diff.items()})
    db.commit()
    return {"updated": sorted(diff), "items": app_settings.describe(db, user)}


# ---------------------------------------------------------------- Nhật ký (UC-06)
def _audit_filters(action: str | None = None, entity: str | None = None, user_id: int | None = None,
                   date_from: str | None = None, date_to: str | None = None, q: str | None = None,
                   branch_id: int | None = Query(None, description="Lọc theo chi nhánh (quản trị viên); 0 = không thuộc chi nhánh nào")) -> dict:
    return {"action": action, "entity": entity, "user_id": user_id, "date_from": date_from, "date_to": date_to,
            "q": q, "branch_id": branch_id}


@router.get("/audit-logs")
def audit_logs(f: dict = Depends(_audit_filters), page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=200),
               db: Session = Depends(get_db), user: User = Depends(ADMIN_OR_OWNER)):
    """Quản trị viên xem toàn bộ, tách theo chi nhánh; chủ cửa hàng chỉ xem nhật ký nghiệp vụ (bảng 4.2)
    của chi nhánh mình (chủ chưa được gán chi nhánh thì không giới hạn chi nhánh).
    q: tìm theo tên người thực hiện, mã / tên bản ghi bị tác động hoặc giá trị trước / sau."""
    stmt = audit_view.filtered(user, **f)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(AuditLog.id.desc()).offset((page - 1) * size).limit(size)).all()
    names = audit_view.targets(db, rows)

    # Lựa chọn cho bộ lọc, trong phạm vi người xem được phép
    scope = audit_view.scoped(user).subquery()
    actions = db.scalars(select(scope.c.action).distinct().order_by(scope.c.action)).all()
    entities = db.scalars(select(scope.c.entity).distinct().order_by(scope.c.entity)).all()
    actors = db.execute(select(User.id, User.full_name).where(User.id.in_(select(scope.c.user_id)))
                        .order_by(User.full_name)).all()
    out = {"total": total, "items": [audit_view.item(r, names.get(r.id)) for r in rows],
           "actions": [{"value": a, "label": audit_view.ACTION_LABELS.get(a, a)} for a in actions],
           "entities": [{"value": e, "label": audit_view.ENTITY_LABELS.get(e, e)} for e in entities],
           "users": [{"id": i, "name": n} for i, n in actors],
           "branches": [], "branch_counts": {}, "branch_name": user.branch_name if user.role == "owner" else None}
    if user.role == "admin":  # tab chi nhánh kèm số dòng (cùng bộ lọc, mọi chi nhánh)
        out["branches"] = [{"id": b.id, "name": b.name, "is_active": b.is_active}
                           for b in db.scalars(select(Branch).order_by(Branch.id))]
        out["branch_counts"] = audit_view.branch_counts(db, audit_view.filtered(user, **{**f, "branch_id": None}))
    return out


@router.get("/audit-logs/export")
def audit_logs_export(f: dict = Depends(_audit_filters), db: Session = Depends(get_db),
                      user: User = Depends(ADMIN_OR_OWNER)):
    """Xuất nhật ký đang lọc ra Excel (tối đa 10.000 dòng mới nhất)."""
    rows = db.scalars(audit_view.filtered(user, **f).order_by(AuditLog.id.desc()).limit(10_000)).all()
    names = audit_view.targets(db, rows)
    items = [audit_view.item(r, names.get(r.id)) for r in rows]
    headers = ["Thời điểm", "Chi nhánh", "Người thực hiện", "Đối tượng", "Thao tác", "Trên", "Trước", "Sau", "IP"]
    content = to_xlsx([("Nhat ky thao tac", headers, audit_view.export_rows(items))])
    return Response(content, media_type=MEDIA["xlsx"],
                    headers={"Content-Disposition": f'attachment; filename="nhat-ky-thao-tac-{now():%Y%m%d-%H%M}.xlsx"'})


@router.get("/email-logs")
def email_logs(page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=200),
               db: Session = Depends(get_db), _: User = Depends(ADMIN_OR_OWNER)):
    total = db.scalar(select(func.count(EmailLog.id)))
    rows = db.scalars(select(EmailLog).order_by(EmailLog.id.desc()).offset((page - 1) * size).limit(size)).all()
    return {"total": total, "items": [{"id": r.id, "to_email": r.to_email, "subject": r.subject,
                                       "mail_type": r.mail_type, "status": r.status,
                                       "error_message": r.error_message, "created_at": r.created_at} for r in rows]}


# ---------------------------------------------------------------- Sao lưu, khôi phục (FR-SYS-04)
REQUIRED_TABLES = {"users", "products", "invoices", "invoice_items", "customers"}


def _sqlite_conn(db: Session) -> sqlite3.Connection:
    if db.get_bind().dialect.name != "sqlite":
        raise HTTPException(400, "Sao lưu trong ứng dụng chỉ hỗ trợ SQLite. Với PostgreSQL hãy dùng pg_dump")
    return db.connection().connection.dbapi_connection


@router.post("/admin/backup")
def backup(db: Session = Depends(get_db), admin: User = Depends(ADMIN_ONLY)):
    """Tải về bản sao CSDL SQLite nhất quán (dùng API backup của SQLite, an toàn khi đang có người bán hàng)."""
    src = _sqlite_conn(db)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "backup.db"
        dst = sqlite3.connect(path)
        try:
            src.backup(dst)
        finally:
            dst.close()
        content = path.read_bytes()
    audit.log(db, admin, "DB_BACKUP", "database", None, new={"bytes": len(content)})
    db.commit()
    name = f"techstoreai-backup-{now():%Y%m%d-%H%M%S}.db"
    return Response(content, media_type="application/vnd.sqlite3",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.post("/admin/restore")
async def restore(file: UploadFile = File(...), db: Session = Depends(get_db), admin: User = Depends(ADMIN_ONLY)):
    """Khôi phục từ tệp sao lưu. Kiểm tra tệp là CSDL SQLite của hệ thống trước khi ghi đè."""
    data = await file.read()
    if not data.startswith(b"SQLite format 3\x00"):
        raise HTTPException(400, "Tệp không phải bản sao lưu SQLite hợp lệ")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "restore.db"
        path.write_bytes(data)
        src = sqlite3.connect(path)
        try:
            tables = {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not REQUIRED_TABLES <= tables:
                raise HTTPException(400, "Tệp sao lưu thiếu bảng dữ liệu của hệ thống")
            if src.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise HTTPException(400, "Tệp sao lưu bị hỏng (integrity_check thất bại)")
            admin_id, admin_name = admin.id, admin.username
            db.commit()
            dst = _sqlite_conn(db)
            src.backup(dst)
        finally:
            src.close()
    db.rollback()
    db.expire_all()
    from app.database import ensure_schema
    ensure_schema(db.get_bind())  # bản sao lưu cũ có thể thiếu cột mới
    restored_admin = db.get(User, admin_id)
    audit.log(db, restored_admin, "DB_RESTORE", "database", None, new={"file": file.filename, "by": admin_name})
    db.commit()
    return {"ok": True, "message": "Đã khôi phục dữ liệu. Mọi người dùng nên đăng nhập lại"}
