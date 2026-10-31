"""Mỗi chi nhánh độc lập: chủ cửa hàng và nhân viên chỉ đọc / ghi dữ liệu nghiệp vụ của chi nhánh mình.

Cách làm (không phải sửa từng API):
- get_current_user gọi set_scope(db, user.branch_id) cho chủ cửa hàng / nhân viên.
- Mọi câu SELECT của ORM trên phiên đó tự thêm điều kiện branch_id = chi nhánh (with_loader_criteria) cho các
  bảng kế thừa BranchOwned, kể cả khi nạp quan hệ (invoice.items...) và db.get().
- Bản ghi mới của các bảng đó tự gắn branch_id trước khi ghi (before_flush).
- Quản trị viên, vòng chạy nền, script: không đặt phạm vi, thấy mọi chi nhánh.
- Chi nhánh chính: chủ cửa hàng ở đó gọi API báo cáo / hóa đơn kèm ?branch=all hoặc ?branch=<id> để XEM số liệu
  mọi chi nhánh hoặc một chi nhánh khác (view_branches). Chỉ phạm vi đọc đổi; bản ghi mới vẫn gắn chi nhánh của
  người dùng, cấu hình cửa hàng vẫn của chi nhánh mình.

Mã chứng từ, SKU, mã vạch, serial không trùng trên toàn hệ thống: chỗ sinh mã / kiểm tra trùng chạy truy vấn với
ALL_BRANCHES để bỏ qua bộ lọc.
"""
from sqlalchemy import event, inspect, select, text, update
from sqlalchemy.orm import Session, with_loader_criteria

from app.models import AuditLog, Base, Branch, BranchOwned, BranchStock, Product, User

ALL_BRANCHES = {"all_branches": True}  # .execution_options(**ALL_BRANCHES): truy vấn trên mọi chi nhánh
DEFAULT_BRANCH = "Chi nhánh chính"
_KEY = "branch_scope"   # phạm vi đọc: id chi nhánh, None hoặc _ALL
_HOME = "branch_home"   # chi nhánh của người dùng: gắn cho bản ghi mới, chọn cấu hình cửa hàng
_ALL = "all"


def set_scope(db: Session, branch_id: int | None) -> None:
    """Giới hạn phiên CSDL trong một chi nhánh (None: chỉ thấy dữ liệu chưa thuộc chi nhánh nào)."""
    db.info[_KEY] = branch_id
    db.info[_HOME] = branch_id


def view_branches(db: Session, branch_id: int | None) -> None:
    """Chỉ đổi phạm vi ĐỌC của phiên: None = mọi chi nhánh, số = một chi nhánh. Dùng cho chi nhánh chính."""
    db.info[_KEY] = _ALL if branch_id is None else branch_id


def viewing_other(db: Session) -> bool:
    """Phiên đang xem dữ liệu ngoài chi nhánh của mình (mọi chi nhánh hoặc chi nhánh khác)."""
    return _KEY in db.info and db.info[_KEY] != db.info.get(_HOME, db.info[_KEY])


def viewing_all(db: Session) -> bool:
    return db.info.get(_KEY) == _ALL


def current_branch(db: Session) -> int | None:
    """Chi nhánh của người dùng phiên hiện tại; None khi không giới hạn (quản trị viên, chạy nền)."""
    return db.info.get(_HOME, db.info.get(_KEY))


def is_scoped(db: Session) -> bool:
    return _KEY in db.info


@event.listens_for(Session, "do_orm_execute")
def _filter_by_branch(state) -> None:
    if _KEY not in state.session.info or not state.is_select or state.execution_options.get("all_branches"):
        return
    branch = state.session.info[_KEY]
    if branch == _ALL:
        return
    if branch is None:
        criteria = with_loader_criteria(BranchOwned, lambda cls: cls.branch_id.is_(None), include_aliases=True)
    else:
        criteria = with_loader_criteria(BranchOwned, lambda cls: cls.branch_id == branch, include_aliases=True)
    state.statement = state.statement.options(criteria)


@event.listens_for(Session, "before_flush")
def _stamp_branch(session: Session, _ctx, _instances) -> None:
    branch = current_branch(session)
    for obj in list(session.new):
        # Sản phẩm mới tạo kèm Product(stock=n): tồn ban đầu thuộc chi nhánh người tạo
        if isinstance(obj, Product) and obj.__dict__.get("stock"):
            session.add(BranchStock(product=obj, stock=obj.__dict__["stock"], branch_id=branch))
    if branch is None:
        return
    for obj in session.new:
        if isinstance(obj, BranchOwned) and obj.branch_id is None:
            obj.branch_id = branch


def owned_tables() -> list[str]:
    return sorted(m.class_.__tablename__ for m in Base.registry.mappers if issubclass(m.class_, BranchOwned))


def assign_default_branch(bind) -> None:
    """Chạy khi khởi động: dữ liệu nghiệp vụ và tài khoản chủ cửa hàng / nhân viên chưa thuộc chi nhánh nào
    (CSDL từ trước khi có chi nhánh, dữ liệu mẫu) được gom về "Chi nhánh chính".
    Nhật ký email không gom (email đặt lại mật khẩu... không thuộc chi nhánh); nhật ký AI theo chi nhánh của người hỏi."""
    with Session(bind) as db:
        tables = [t for t in owned_tables() if t not in ("email_logs", "ai_logs")]
        existing = set(inspect(bind).get_table_names())
        orphan_users = db.scalar(select(User.id).where(User.role != "admin", User.branch_id.is_(None)).limit(1))
        orphan_data = any(db.execute(text(f"SELECT 1 FROM {t} WHERE branch_id IS NULL LIMIT 1")).first()
                          for t in tables if t in existing)
        if orphan_users is None and not orphan_data:
            _ensure_main(db)
            return
        branch = db.scalar(select(Branch).where(Branch.name == DEFAULT_BRANCH))
        if branch is None:
            branch = Branch(name=DEFAULT_BRANCH, is_main=db.scalar(select(Branch.id).limit(1)) is None)
            db.add(branch)
            db.flush()
        moved = select(User.id).where(User.role != "admin", User.branch_id.is_(None))
        db.execute(update(AuditLog).where(AuditLog.branch_id.is_(None), AuditLog.user_id.in_(moved))
                   .values(branch_id=branch.id))
        db.execute(update(User).where(User.role != "admin", User.branch_id.is_(None)).values(branch_id=branch.id))
        for t in tables:
            if t in existing:
                db.execute(text(f"UPDATE {t} SET branch_id = :b WHERE branch_id IS NULL"), {"b": branch.id})
        db.execute(text("UPDATE ai_logs SET branch_id = (SELECT u.branch_id FROM users u WHERE u.id = ai_logs.user_id) "
                        "WHERE branch_id IS NULL"))
        db.commit()
        _ensure_main(db)


def _ensure_main(db: Session) -> None:
    """Luôn có một chi nhánh chính khi đã có chi nhánh: ưu tiên "Chi nhánh chính", không thì chi nhánh tạo đầu tiên."""
    if db.scalar(select(Branch.id).where(Branch.is_main.is_(True)).limit(1)) is not None:
        return
    branch = (db.scalar(select(Branch).where(Branch.name == DEFAULT_BRANCH))
              or db.scalar(select(Branch).order_by(Branch.id).limit(1)))
    if branch is not None:
        branch.is_main = True
        db.commit()
