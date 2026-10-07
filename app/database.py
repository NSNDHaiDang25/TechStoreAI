from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings
from app.services import demo_names


class Base(DeclarativeBase):
    pass


def make_engine(url: str, **kwargs):
    connect_args = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        db_path = url.replace("sqlite:///", "", 1)
        if db_path and db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, connect_args=connect_args, **kwargs)
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _):
            dbapi_conn.execute("PRAGMA foreign_keys=ON")
            dbapi_conn.execute("PRAGMA busy_timeout=5000")  # SRS 2.6: chờ tối đa 5 giây khi quầy khác đang ghi
            if db_path and db_path != ":memory:":
                dbapi_conn.execute("PRAGMA journal_mode=WAL")
    return engine


def lock_for_write(db) -> None:
    """Giành khóa ghi của SQLite ngay đầu giao dịch (FR-SAL-12, NFR 7.6).

    Mã chứng từ (HD-yyyyMMdd-nnnn...) lấy số lớn nhất đã dùng cộng 1. Nếu hai quầy cùng đọc số lớn nhất rồi mới
    ghi thì trùng mã. Một câu UPDATE không đổi dòng nào làm driver mở giao dịch và SQLite cấp khóa RESERVED ngay,
    quầy sau chờ (busy_timeout 5 giây) đến khi quầy trước commit rồi mới đọc, nên mã luôn tăng dần, không trùng.
    CSDL khác SQLite đã có ràng buộc UNIQUE và cơ chế thử lại ở router nên không cần bước này.
    """
    bind = db.get_bind()
    if bind.dialect.name == "sqlite":
        db.execute(text("UPDATE products SET id = id WHERE 1 = 0"))


engine = make_engine(settings.DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


# Cột được thêm sau phiên bản đầu. create_all() không sửa bảng đã có nên bổ sung bằng ALTER TABLE,
# giúp CSDL cũ vẫn chạy mà không phải xóa dữ liệu.
ADDED_COLUMNS = {
    "users": {
        "pending": "BOOLEAN NOT NULL DEFAULT FALSE",
        "email": "VARCHAR(100)", "phone": "VARCHAR(15)",
        "must_change_password": "BOOLEAN NOT NULL DEFAULT FALSE",
        "failed_login_count": "INTEGER NOT NULL DEFAULT 0",
        "locked_until": "DATETIME", "last_login_at": "DATETIME", "updated_at": "DATETIME",
    },
    "categories": {
        "default_vat_rate": "INTEGER NOT NULL DEFAULT 10",
        "default_warranty_months": "INTEGER NOT NULL DEFAULT 12",
        "is_active": "BOOLEAN NOT NULL DEFAULT TRUE", "name_en": "VARCHAR(100)",
    },
    "products": {
        "image_url": "VARCHAR(255)", "name_en": "VARCHAR(200)", "barcode": "VARCHAR(20)", "brand": "VARCHAR(50)",
        "vat_rate": "INTEGER NOT NULL DEFAULT 10", "track_serial": "BOOLEAN NOT NULL DEFAULT FALSE",
        "warranty_months": "INTEGER NOT NULL DEFAULT 12",
    },
    "customers": {
        "birthday": "DATE", "tier_id": "INTEGER", "loyalty_points": "INTEGER NOT NULL DEFAULT 0",
        "total_spent": "INTEGER NOT NULL DEFAULT 0", "is_active": "BOOLEAN NOT NULL DEFAULT TRUE",
        "updated_at": "DATETIME",
    },
    "import_receipts": {
        "supplier_id": "INTEGER", "status": "VARCHAR(15) NOT NULL DEFAULT 'confirmed'",
        "received_at": "DATETIME", "cancelled_at": "DATETIME", "cancel_reason": "VARCHAR(255)",
    },
    "import_items": {"serials": "JSON"},
    "invoices": {
        "cash_received": "INTEGER", "payment_ref": "VARCHAR(50)",
        "promo_discount": "INTEGER NOT NULL DEFAULT 0", "points_discount": "INTEGER NOT NULL DEFAULT 0",
        "vat_amount": "INTEGER NOT NULL DEFAULT 0", "promotion_id": "INTEGER",
        "points_used": "INTEGER NOT NULL DEFAULT 0", "points_earned": "INTEGER NOT NULL DEFAULT 0",
        "paid_at": "DATETIME", "cancelled_by": "INTEGER", "cancel_requested_by": "INTEGER",
        "cancel_requested_at": "DATETIME", "print_count": "INTEGER NOT NULL DEFAULT 0",
    },
    "invoice_items": {
        "serial_id": "INTEGER", "discount_amount": "INTEGER NOT NULL DEFAULT 0",
        "vat_rate": "INTEGER NOT NULL DEFAULT 10", "vat_amount": "INTEGER NOT NULL DEFAULT 0",
        "returned_qty": "INTEGER NOT NULL DEFAULT 0", "warranty_months": "INTEGER NOT NULL DEFAULT 12",
        "promotion_id": "INTEGER",
    },
}

# Chạy một lần khi cột tương ứng vừa được thêm: chuyển dữ liệu cũ sang cách lưu mới.
DATA_MIGRATIONS = {
    ("invoices", "paid_at"): [
        "UPDATE invoices SET paid_at = created_at WHERE status = 'paid' AND paid_at IS NULL",
        "UPDATE invoices SET payment_method = 'bank_transfer' WHERE payment_method IN ('transfer', 'qr')",
        "UPDATE invoices SET promo_discount = discount",
    ],
    ("customers", "total_spent"): [
        "UPDATE customers SET total_spent = (SELECT COALESCE(SUM(total), 0) FROM invoices "
        "WHERE invoices.customer_id = customers.id AND invoices.status = 'paid')",
    ],
    ("import_receipts", "received_at"): ["UPDATE import_receipts SET received_at = created_at"],
    # Bản cũ chưa tách VAT: giá đã gồm VAT 10% (giả định mặc định của SRS), tách ra để báo cáo doanh thu chưa VAT
    ("invoices", "vat_amount"): ["UPDATE invoices SET vat_amount = CAST(ROUND(total * 10.0 / 110) AS INTEGER)"],
    ("invoice_items", "vat_amount"): [
        "UPDATE invoice_items SET vat_amount = CAST(ROUND(line_total * 10.0 / 110) AS INTEGER)"],
    # Tên tiếng Anh cho sản phẩm, nhóm hàng mẫu (giao diện tiếng Anh)
    **demo_names.migration_sql(),
}


def ensure_schema(bind) -> None:
    Base.metadata.create_all(bind)
    inspector = inspect(bind)
    with bind.begin() as conn:
        for table, columns in ADDED_COLUMNS.items():
            existing = {c["name"] for c in inspector.get_columns(table)}
            for name, ddl in columns.items():
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
                    for sql in DATA_MIGRATIONS.get((table, name), []):
                        conn.execute(text(sql))
        from app.ai.text_to_sql import ensure_views
        ensure_views(conn, recreate=True)  # view v_ai_* cho hỏi đáp dữ liệu (SRS 6.5, 7.5)
    from app.services.bootstrap import ensure_reference_data
    ensure_reference_data(bind)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
