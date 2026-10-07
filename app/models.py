"""Mô hình dữ liệu (SRS chương 7). Tiền tệ lưu dạng số nguyên (VND) để tránh sai số dấu phẩy động.

Tên cột giữ theo phiên bản đầu để CSDL cũ vẫn chạy; bảng đối chiếu với tên trong SRS xem docs/05_doi_chieu_SRS.md.
"""
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

ROLES = ("admin", "owner", "staff")
PAYMENT_METHODS = ("cash", "bank_transfer", "card")
CUSTOMER_GROUPS = ("regular", "vip", "wholesale")

# Trạng thái hóa đơn (bảng 3.2). PAID_STATES: hóa đơn đã phát sinh doanh thu.
INVOICE_STATES = ("draft", "pending_payment", "paid", "partially_returned", "fully_returned", "cancelled")
PAID_STATES = ("paid", "partially_returned", "fully_returned")
SERIAL_STATES = ("in_stock", "sold", "returned", "defective", "in_warranty")
TICKET_STATES = ("received", "in_repair", "waiting_parts", "done", "rejected", "returned")
TICKET_OPEN = ("received", "in_repair", "waiting_parts")


# Giờ cửa hàng: Việt Nam UTC+7 (không đổi giờ mùa hè). Không dùng giờ hệ thống vì máy chủ deploy
# (Render, Docker) chạy theo UTC: phiếu tạo lúc 10:41 sẽ bị lưu thành 03:41, sau 17:00 còn sai cả ngày.
SHOP_TZ = timezone(timedelta(hours=7), "ICT")


def now() -> datetime:
    """Giờ Việt Nam hiện tại, không kèm múi giờ (cùng dạng dữ liệu đã lưu). Ngày hôm nay: now().date()."""
    return datetime.now(SHOP_TZ).replace(tzinfo=None, microsecond=0)


# ======================================================================= Hệ thống và bảo mật
class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20), default="staff")  # admin | owner | staff (ADMIN/OWNER/STAFF)
    email: Mapped[str | None] = mapped_column(String(100))
    phone: Mapped[str | None] = mapped_column(String(15))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Tự đăng ký ở màn hình đăng nhập: bị khóa và chờ quản trị viên duyệt (phân biệt với tài khoản bị khóa thường)
    pending: Mapped[bool] = mapped_column(Boolean, default=False)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)  # FR-USR-02
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0)       # FR-AUT-03
    locked_until: Mapped[datetime | None] = mapped_column(DateTime)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=now)


class FaceProfile(Base):
    """Mẫu khuôn mặt để đăng nhập Face ID (chủ cửa hàng, quản trị viên). Chỉ lưu vector đặc trưng 128 chiều, không lưu ảnh."""
    __tablename__ = "face_profiles"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    embedding: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class PasswordReset(Base):
    """Mã đặt lại mật khẩu gửi qua email. Chỉ lưu mã đã băm, mã gốc chỉ có trong email."""
    __tablename__ = "password_resets"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    code_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    used: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class RevokedToken(Base):
    """JWT đã thu hồi khi đăng xuất (FR-AUT-05)."""
    __tablename__ = "revoked_tokens"
    jti: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime)


class Setting(Base):
    """Tham số cấu hình (bảng 2.5). Giá trị mặc định ở app/services/app_settings.py."""
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(String(200))
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)


class AuditLog(Base):
    """Nhật ký thao tác nhạy cảm (FR-SYS-03)."""
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(50), index=True)
    entity: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[int | None] = mapped_column(Integer)
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    ip_address: Mapped[str | None] = mapped_column(String(45))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)
    user: Mapped[User | None] = relationship()


class EmailLog(Base):
    __tablename__ = "email_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    to_email: Mapped[str] = mapped_column(String(100))
    subject: Mapped[str] = mapped_column(String(200))
    mail_type: Mapped[str] = mapped_column(String(30))  # invoice | warranty | reset_password | account
    status: Mapped[str] = mapped_column(String(10))  # sent | failed
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class AILog(Base):
    """Nhật ký mỗi lượt gọi AI (BR-44). Câu hỏi đã che số điện thoại, email."""
    __tablename__ = "ai_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    feature: Mapped[str] = mapped_column(String(10))  # advisor | report | qa | assistant
    prompt_version: Mapped[str] = mapped_column(String(10), default="-")
    model_name: Mapped[str] = mapped_column(String(50), default="-")
    question: Mapped[str] = mapped_column(Text)
    generated_sql: Mapped[str | None] = mapped_column(Text)
    response: Mapped[str | None] = mapped_column(Text)
    # success | fallback | timeout | rate_limited | invalid_format | rejected_sql | disabled | error
    status: Mapped[str] = mapped_column(String(15))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)
    user: Mapped[User] = relationship()


# ======================================================================= Danh mục hàng hóa
class Category(Base):
    __tablename__ = "categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    name_en: Mapped[str | None] = mapped_column(String(100))  # tên hiển thị khi giao diện tiếng Anh
    description: Mapped[str | None] = mapped_column(String(255))
    default_vat_rate: Mapped[int] = mapped_column(Integer, default=10)
    default_warranty_months: Mapped[int] = mapped_column(Integer, default=12)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    products: Mapped[list["Product"]] = relationship(back_populates="category")


class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True, index=True)  # SKU
    barcode: Mapped[str | None] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    name_en: Mapped[str | None] = mapped_column(String(200))  # tên hiển thị khi giao diện tiếng Anh
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"))
    brand: Mapped[str | None] = mapped_column(String(50))
    sale_price: Mapped[int] = mapped_column(Integer, default=0)  # đã gồm VAT (BR-01)
    cost_price: Mapped[int] = mapped_column(Integer, default=0)  # giá vốn bình quân (BR-19)
    vat_rate: Mapped[int] = mapped_column(Integer, default=10)
    stock: Mapped[int] = mapped_column(Integer, default=0)
    min_stock: Mapped[int] = mapped_column(Integer, default=5)
    track_serial: Mapped[bool] = mapped_column(Boolean, default=False)
    warranty_months: Mapped[int] = mapped_column(Integer, default=12)
    description: Mapped[str | None] = mapped_column(Text)
    image_url: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | inactive | discontinued
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)
    category: Mapped[Category | None] = relationship(back_populates="products")


class ProductSerial(Base):
    """Serial hoặc IMEI từng máy (FR-PRD-09)."""
    __tablename__ = "product_serials"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    serial_no: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(15), default="in_stock")  # SERIAL_STATES
    purchase_item_id: Mapped[int | None] = mapped_column(ForeignKey("import_items.id"))
    invoice_item_id: Mapped[int | None] = mapped_column(ForeignKey("invoice_items.id", use_alter=True))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    product: Mapped[Product] = relationship()


# ======================================================================= Nhập hàng và kho
class Supplier(Base):
    __tablename__ = "suppliers"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(150))
    contact_name: Mapped[str | None] = mapped_column(String(100))
    phone: Mapped[str | None] = mapped_column(String(15))
    email: Mapped[str | None] = mapped_column(String(100))
    address: Mapped[str | None] = mapped_column(String(255))
    tax_code: Mapped[str | None] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(10), default="active")  # active | inactive
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class ImportReceipt(Base):
    """Phiếu nhập hàng (purchase_orders trong SRS): draft -> confirmed -> cancelled."""
    __tablename__ = "import_receipts"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"), index=True)
    supplier: Mapped[str | None] = mapped_column(String(150))  # tên nhà cung cấp (phiếu cũ chỉ có tên)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(15), default="confirmed")  # draft | confirmed | cancelled
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)
    received_at: Mapped[datetime | None] = mapped_column(DateTime)
    total: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[str | None] = mapped_column(String(255))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime)
    cancel_reason: Mapped[str | None] = mapped_column(String(255))
    user: Mapped[User] = relationship()
    supplier_ref: Mapped[Supplier | None] = relationship()
    items: Mapped[list["ImportItem"]] = relationship(
        back_populates="receipt", cascade="all, delete-orphan", order_by="ImportItem.id"
    )


class ImportItem(Base):
    __tablename__ = "import_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    receipt_id: Mapped[int] = mapped_column(ForeignKey("import_receipts.id", ondelete="CASCADE"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_cost: Mapped[int] = mapped_column(Integer, default=0)  # nhân viên lập nháp chưa có giá nhập
    line_total: Mapped[int] = mapped_column(Integer, default=0)
    serials: Mapped[list | None] = mapped_column(JSON)  # serial nhập kèm (phiếu nháp), tạo product_serials khi xác nhận
    receipt: Mapped[ImportReceipt] = relationship(back_populates="items")
    product: Mapped[Product] = relationship()


class StockMovement(Base):
    """Thẻ kho: mọi thay đổi tồn kho đều ghi lại tại đây (BR-17)."""
    __tablename__ = "stock_movements"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    change: Mapped[int] = mapped_column(Integer)  # dương = nhập, âm = xuất
    stock_after: Mapped[int] = mapped_column(Integer)  # tồn trước = stock_after - change
    # import | import_cancel | sale | cancel | edit | return | adjust
    type: Mapped[str] = mapped_column(String(20))
    ref_code: Mapped[str | None] = mapped_column(String(30))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    note: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)
    product: Mapped[Product] = relationship()


# ======================================================================= Khách hàng và khuyến mãi
class CustomerTier(Base):
    __tablename__ = "customer_tiers"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(30), unique=True)
    min_total_spent: Mapped[int] = mapped_column(Integer, default=0)
    points_multiplier: Mapped[float] = mapped_column(Float, default=1.0)


class Customer(Base):
    __tablename__ = "customers"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100), index=True)
    phone: Mapped[str | None] = mapped_column(String(20), index=True)
    email: Mapped[str | None] = mapped_column(String(100))
    address: Mapped[str | None] = mapped_column(String(255))
    birthday: Mapped[date | None] = mapped_column(Date)
    group: Mapped[str] = mapped_column(String(20), default="regular")
    tier_id: Mapped[int | None] = mapped_column(ForeignKey("customer_tiers.id"))
    loyalty_points: Mapped[int] = mapped_column(Integer, default=0)
    total_spent: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=now)
    tier: Mapped[CustomerTier | None] = relationship()
    invoices: Mapped[list["Invoice"]] = relationship(back_populates="customer")


class LoyaltyTransaction(Base):
    __tablename__ = "loyalty_transactions"
    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    invoice_id: Mapped[int | None] = mapped_column(ForeignKey("invoices.id"))
    txn_type: Mapped[str] = mapped_column(String(15))  # earn | redeem | reverse_earn | reverse_redeem | adjust
    points: Mapped[int] = mapped_column(Integer)
    balance_after: Mapped[int] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(String(255))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Promotion(Base):
    __tablename__ = "promotions"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str | None] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(150))
    promo_type: Mapped[str] = mapped_column(String(15))  # percent | fixed_amount
    scope: Mapped[str] = mapped_column(String(10))  # product | category | invoice
    target_id: Mapped[int | None] = mapped_column(Integer)
    discount_value: Mapped[int] = mapped_column(Integer)
    max_discount: Mapped[int | None] = mapped_column(Integer)
    min_invoice_amount: Mapped[int] = mapped_column(Integer, default=0)
    requires_code: Mapped[bool] = mapped_column(Boolean, default=False)
    usage_limit: Mapped[int | None] = mapped_column(Integer)
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    start_at: Mapped[datetime] = mapped_column(DateTime)
    end_at: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(10), default="active")  # active | paused | expired
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


# ======================================================================= Bán hàng
class Invoice(Base):
    __tablename__ = "invoices"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))  # cashier_id
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)
    subtotal: Mapped[int] = mapped_column(Integer, default=0)  # tổng thành tiền các dòng, đã gồm VAT
    promo_discount: Mapped[int] = mapped_column(Integer, default=0)  # khuyến mãi + giảm tay
    points_discount: Mapped[int] = mapped_column(Integer, default=0)
    discount: Mapped[int] = mapped_column(Integer, default=0)  # = promo_discount + points_discount
    total: Mapped[int] = mapped_column(Integer, default=0)  # total_amount: khách phải trả
    vat_amount: Mapped[int] = mapped_column(Integer, default=0)
    promotion_id: Mapped[int | None] = mapped_column(ForeignKey("promotions.id"))
    points_used: Mapped[int] = mapped_column(Integer, default=0)
    points_earned: Mapped[int] = mapped_column(Integer, default=0)
    payment_method: Mapped[str] = mapped_column(String(20), default="cash")
    cash_received: Mapped[int | None] = mapped_column(Integer)  # tiền khách đưa (tiền mặt)
    payment_ref: Mapped[str | None] = mapped_column(String(50))  # nội dung CK / mã giao dịch POS
    status: Mapped[str] = mapped_column(String(20), default="paid", index=True)  # INVOICE_STATES
    note: Mapped[str | None] = mapped_column(String(255))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime)
    cancelled_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    cancel_reason: Mapped[str | None] = mapped_column(String(255))
    # Nhân viên gửi yêu cầu hủy hóa đơn đã thanh toán, chủ cửa hàng duyệt (FR-SAL-10)
    cancel_requested_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime)
    print_count: Mapped[int] = mapped_column(Integer, default=0)

    customer: Mapped[Customer | None] = relationship(back_populates="invoices")
    user: Mapped[User] = relationship(foreign_keys=[user_id])
    promotion: Mapped[Promotion | None] = relationship()
    items: Mapped[list["InvoiceItem"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan", order_by="InvoiceItem.id"
    )
    payments: Mapped[list["Payment"]] = relationship(back_populates="invoice", order_by="Payment.id")


class InvoiceItem(Base):
    __tablename__ = "invoice_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    serial_id: Mapped[int | None] = mapped_column(ForeignKey("product_serials.id"))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[int] = mapped_column(Integer)  # đã gồm VAT, chốt lúc bán (BR-02)
    unit_cost: Mapped[int] = mapped_column(Integer, default=0)  # cost_snapshot (BR-20)
    line_total: Mapped[int] = mapped_column(Integer)  # thành tiền gốc = unit_price * quantity
    discount_amount: Mapped[int] = mapped_column(Integer, default=0)  # giảm giá phân bổ cho dòng
    vat_rate: Mapped[int] = mapped_column(Integer, default=10)
    vat_amount: Mapped[int] = mapped_column(Integer, default=0)
    returned_qty: Mapped[int] = mapped_column(Integer, default=0)
    warranty_months: Mapped[int] = mapped_column(Integer, default=12)
    promotion_id: Mapped[int | None] = mapped_column(ForeignKey("promotions.id"))  # khuyến mãi cấp dòng đã áp
    invoice: Mapped[Invoice] = relationship(back_populates="items")
    product: Mapped[Product] = relationship()
    serial: Mapped[ProductSerial | None] = relationship(foreign_keys=[serial_id])

    @property
    def net_total(self) -> int:
        """Số khách thực trả cho dòng (cột 'Còn lại' bảng 3.3)."""
        return self.line_total - self.discount_amount


class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"), index=True)
    method: Mapped[str] = mapped_column(String(15))
    amount: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(12), default="pending")  # pending | confirmed | failed
    reference_code: Mapped[str | None] = mapped_column(String(50))
    qr_payload: Mapped[str | None] = mapped_column(Text)
    confirmed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    invoice: Mapped[Invoice] = relationship(back_populates="payments")


# ======================================================================= Đổi trả và bảo hành
class Return(Base):
    __tablename__ = "returns"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(25), unique=True, index=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), index=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"))
    return_type: Mapped[str] = mapped_column(String(10))  # refund | exchange
    reason: Mapped[str] = mapped_column(String(255))
    refund_amount: Mapped[int] = mapped_column(Integer, default=0)
    points_reversed: Mapped[int] = mapped_column(Integer, default=0)
    new_invoice_id: Mapped[int | None] = mapped_column(ForeignKey("invoices.id"))
    processed_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)
    invoice: Mapped[Invoice] = relationship(foreign_keys=[invoice_id])
    new_invoice: Mapped[Invoice | None] = relationship(foreign_keys=[new_invoice_id])
    user: Mapped[User] = relationship()
    items: Mapped[list["ReturnItem"]] = relationship(back_populates="ret", cascade="all, delete-orphan")


class ReturnItem(Base):
    __tablename__ = "return_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    return_id: Mapped[int] = mapped_column(ForeignKey("returns.id", ondelete="CASCADE"))
    invoice_item_id: Mapped[int] = mapped_column(ForeignKey("invoice_items.id"))
    serial_id: Mapped[int | None] = mapped_column(ForeignKey("product_serials.id"))
    quantity: Mapped[int] = mapped_column(Integer)
    refund_amount: Mapped[int] = mapped_column(Integer, default=0)
    item_condition: Mapped[str] = mapped_column(String(15))  # sellable | defective
    restock: Mapped[bool] = mapped_column(Boolean, default=False)
    ret: Mapped[Return] = relationship(back_populates="items")
    invoice_item: Mapped[InvoiceItem] = relationship()


class Warranty(Base):
    """Hồ sơ bảo hành, tạo khi hóa đơn thanh toán (FR-WAR-01)."""
    __tablename__ = "warranties"
    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_item_id: Mapped[int] = mapped_column(ForeignKey("invoice_items.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    serial_id: Mapped[int | None] = mapped_column(ForeignKey("product_serials.id"), index=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), index=True)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(10), default="active")  # active | expired | void
    invoice_item: Mapped[InvoiceItem] = relationship()
    product: Mapped[Product] = relationship()
    serial: Mapped[ProductSerial | None] = relationship()
    customer: Mapped[Customer | None] = relationship()


class WarrantyTicket(Base):
    __tablename__ = "warranty_tickets"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(25), unique=True, index=True)
    warranty_id: Mapped[int] = mapped_column(ForeignKey("warranties.id"), index=True)
    issue_description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(15), default="received")  # TICKET_STATES
    received_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    received_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    resolution: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    returned_at: Mapped[datetime | None] = mapped_column(DateTime)
    warranty: Mapped[Warranty] = relationship()
    user: Mapped[User] = relationship()


# ======================================================================= Lịch sử trò chuyện AI
class ChatSession(Base):
    """Lịch sử tra cứu AI: mỗi cuộc trò chuyện thuộc về một người dùng."""
    __tablename__ = "chat_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20), index=True)  # assistant | advisor | ask
    title: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)
    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="ChatMessage.id"
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(10))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    meta: Mapped[dict | None] = mapped_column(JSON)  # gợi ý sản phẩm, nguồn (AI/dự phòng), kỳ dữ liệu...
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    session: Mapped[ChatSession] = relationship(back_populates="messages")
