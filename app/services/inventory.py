"""Nghiệp vụ tồn kho, hóa đơn và phiếu nhập.

Mọi thay đổi tồn kho đi qua `change_stock` để luôn có nhật ký StockMovement và
không bao giờ để tồn kho âm. Các hàm ở đây KHÔNG commit; router gọi commit sau khi
toàn bộ nghiệp vụ thành công (một giao dịch duy nhất).
"""
from collections import defaultdict
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from app.models import (
    Category, Customer, ImportItem, ImportReceipt, Invoice, InvoiceItem, Product, StockMovement, User, now,
)
from app.schemas import ImportIn, InvoiceIn, NewProductIn


class BusinessError(Exception):
    """Lỗi nghiệp vụ. Router chuyển thành HTTP 409 (xung đột nghiệp vụ, SRS bảng 8.12) kèm mã lỗi ổn định
    (OUT_OF_STOCK, RETURN_WINDOW_EXPIRED...) theo cấu trúc lỗi chung ở mục 8.4.1."""

    def __init__(self, message: str, code: str = "BUSINESS_RULE", status: int = 409, details: dict | None = None):
        super().__init__(message)
        self.code, self.status, self.details = code, status, details

    def http(self):
        from app.errors import APIError
        return APIError(self.status, str(self), self.code, self.details)


def change_stock(db: Session, product: Product, delta: int, type_: str, ref: str | None,
                 user: User | None, note: str | None = None, at: datetime | None = None) -> None:
    """FR-STK-06: trừ tồn bằng một câu UPDATE có điều kiện stock >= số cần trừ rồi kiểm tra số dòng bị ảnh hưởng,
    không đọc tồn rồi mới ghi lại, nên hai quầy cùng bán chiếc cuối cùng thì chỉ một quầy thành công."""
    stmt = update(Product).where(Product.id == product.id).values(stock=Product.stock + delta)
    if delta < 0:
        stmt = stmt.where(Product.stock >= -delta)
    result = db.execute(stmt.execution_options(synchronize_session=False))
    if result.rowcount != 1:
        current = db.scalar(select(Product.stock).where(Product.id == product.id))
        raise BusinessError(f"Sản phẩm '{product.name}' không đủ tồn kho (còn {current}, cần {-delta})", "OUT_OF_STOCK",
                            details={"product_id": product.id, "available": current, "requested": -delta})
    new_stock = db.scalar(select(Product.stock).where(Product.id == product.id))
    set_committed_value(product, "stock", new_stock)
    db.add(StockMovement(
        product_id=product.id, change=delta, stock_after=new_stock, type=type_, ref_code=ref,
        user_id=user.id if user else None, note=note, created_at=at or now(),
    ))


def _lock_products(db: Session, product_ids) -> dict[int, Product]:
    products = db.scalars(select(Product).where(Product.id.in_(set(product_ids))).with_for_update()).all()
    found = {p.id: p for p in products}
    missing = set(product_ids) - found.keys()
    if missing:
        raise BusinessError(f"Không tìm thấy sản phẩm id {sorted(missing)}", "NOT_FOUND", 404)
    return found


def create_invoice(db: Session, data: InvoiceIn, user: User, at: datetime | None = None) -> Invoice:
    """Giữ cho mã cũ (seed, test): chốt hóa đơn qua app.services.sales."""
    from app.services import sales
    return sales.checkout(db, data, user, at=at)[0]


def create_import(db: Session, data: ImportIn, user: User, at: datetime | None = None) -> ImportReceipt:
    """Phiếu nhập kiểu cũ (/api/imports): lập và xác nhận nhập kho ngay, nhà cung cấp chỉ ghi tên."""
    from app.schemas import PurchaseItemIn, PurchaseOrderIn
    from app.services import purchasing
    po = PurchaseOrderIn(supplier_id=data.supplier_id, supplier_name=data.supplier, note=data.note, confirm=True,
                         items=[PurchaseItemIn(product_id=i.product_id, new_product=i.new_product, quantity=i.quantity,
                                               unit_cost=i.unit_cost, serials=i.serials) for i in data.items])
    return purchasing.create(db, po, user, at, require_supplier=False)


def _new_product_code(db: Session) -> str:
    """Mã tự sinh cho sản phẩm tạo khi nhập hàng: SP0001, SP0002..."""
    nums = [int(c[2:]) for c in db.scalars(select(Product.code).where(Product.code.like("SP%"))) if c[2:].isdigit()]
    return f"SP{max(nums, default=0) + 1:04d}"


def _create_product(db: Session, spec: NewProductIn, unit_cost: int) -> Product:
    """Tạo sản phẩm mới ngay trong phiếu nhập (tồn ban đầu 0, phiếu nhập sẽ cộng tồn)."""
    name = " ".join(spec.name.split())
    if name.casefold() in {n.casefold() for n in db.scalars(select(Product.name))}:
        raise BusinessError(f"Sản phẩm '{name}' đã có trong danh mục, hãy chọn sản phẩm có sẵn thay vì tạo mới")
    code = (spec.code or "").strip().upper() or _new_product_code(db)
    if db.scalar(select(Product.id).where(func.upper(Product.code) == code)):
        raise BusinessError(f"Mã sản phẩm '{code}' đã tồn tại")
    if spec.category_id is not None and db.get(Category, spec.category_id) is None:
        raise BusinessError("Nhóm hàng không tồn tại")
    cat = db.get(Category, spec.category_id) if spec.category_id else None
    product = Product(code=code, name=name, category_id=spec.category_id, sale_price=spec.sale_price,
                      cost_price=unit_cost, stock=0, min_stock=spec.min_stock, track_serial=spec.track_serial,
                      vat_rate=cat.default_vat_rate if cat else 10,
                      warranty_months=cat.default_warranty_months if cat else 12,
                      description=(spec.description or "").strip() or None, status="active")
    db.add(product)
    db.flush()
    return product


def adjust_stock(db: Session, product: Product, new_stock: int, note: str, user: User) -> None:
    """FR-STK-04: kiểm kê, điều chỉnh tồn kèm lý do. Hàng theo serial thì tồn đi theo serial (BR-18)."""
    if product.track_serial:
        raise BusinessError("Sản phẩm quản lý theo serial: tồn kho thay đổi qua phiếu nhập, bán hàng, đổi trả "
                            "hoặc đổi trạng thái serial")
    delta = new_stock - product.stock
    if delta:
        old = product.stock
        change_stock(db, product, delta, "adjust", None, user, note=note)
        from app.services import audit
        audit.log(db, user, "STOCK_ADJUST", "products", product.id, old={"stock": old},
                  new={"stock": new_stock, "note": note})
