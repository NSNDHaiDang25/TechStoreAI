"""Nhà cung cấp và phiếu nhập hàng (SRS 3.2.2, 5.12, 5.13; BR-19, BR-21, BR-22).

Phiếu nhập có ba trạng thái: draft (nháp, chưa đổi tồn) -> confirmed (cộng tồn, cập nhật giá vốn bình quân,
tạo serial) -> cancelled. Các hàm không commit, router commit khi toàn bộ nghiệp vụ thành công.
"""
import re
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ImportItem, ImportReceipt, Product, ProductSerial, Supplier, User, now
from app.schemas import PurchaseOrderIn
from app.services import audit
from app.services.codes import next_code
from app.services.inventory import BusinessError, _create_product, _lock_products, change_stock

SERIAL_RE = re.compile(r"^[A-Za-z0-9\-/]{5,50}$")


def luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def clean_serial(raw: str) -> str:
    """Bảng 5.18: serial 5-50 ký tự chữ và số; chuỗi đúng 15 chữ số được coi là IMEI và phải qua kiểm tra Luhn."""
    s = raw.strip().upper()
    if not SERIAL_RE.match(s):
        raise BusinessError(f"Serial '{raw.strip()}' không hợp lệ (5-50 ký tự chữ và số)")
    if s.isdigit() and len(s) == 15 and not luhn_ok(s):
        raise BusinessError(f"IMEI '{s}' không hợp lệ (sai số kiểm tra Luhn)")
    return s


# ---------------------------------------------------------------- Nhà cung cấp
def next_supplier_code(db: Session) -> str:
    nums = [int(c[3:]) for c in db.scalars(select(Supplier.code).where(Supplier.code.like("NCC%"))) if c[3:].isdigit()]
    return f"NCC{max(nums, default=0) + 1:02d}"


def _active_supplier(db: Session, supplier_id: int | None) -> Supplier:
    sup = db.get(Supplier, supplier_id) if supplier_id else None
    if sup is None:
        raise BusinessError("Phiếu nhập phải chọn nhà cung cấp")
    if sup.status != "active":
        raise BusinessError(f"Nhà cung cấp '{sup.name}' đang ngừng hợp tác")  # BR-21
    return sup


# ---------------------------------------------------------------- Phiếu nhập
def _fill_items(db: Session, po: ImportReceipt, data: PurchaseOrderIn, user: User, keep_cost: dict[int, int]) -> None:
    """Tạo các dòng phiếu từ dữ liệu gửi lên. Nhân viên không gửi giá nhập: giữ giá cũ của dòng cùng sản phẩm."""
    products = _lock_products(db, [i.product_id for i in data.items if i.product_id is not None]) \
        if any(i.product_id for i in data.items) else {}
    created: dict[str, Product] = {}
    seen_serials: set[str] = set()
    total = 0
    for item in data.items:
        if item.new_product is not None:
            if user.role == "staff":
                raise BusinessError("Nhân viên không được tạo sản phẩm mới, hãy nhờ chủ cửa hàng")
            key = " ".join(item.new_product.name.split()).casefold()
            if key not in created:
                created[key] = _create_product(db, item.new_product, item.unit_cost or 0)
            product = created[key]
        else:
            product = products[item.product_id]
        serials = [clean_serial(s) for s in item.serials if s.strip()]
        if serials and not product.track_serial:
            raise BusinessError(f"Sản phẩm '{product.name}' không quản lý serial, bỏ danh sách serial")
        if len(serials) > item.quantity:
            raise BusinessError(f"'{product.name}': nhập {len(serials)} serial nhưng số lượng chỉ {item.quantity}")
        if len(set(serials)) != len(serials) or seen_serials & set(serials):
            raise BusinessError("Danh sách serial trong phiếu bị trùng")
        seen_serials.update(serials)
        cost = item.unit_cost if user.role != "staff" else None
        if cost is None:
            cost = keep_cost.get(product.id, 0)
        line_total = cost * item.quantity
        total += line_total
        po.items.append(ImportItem(product_id=product.id, quantity=item.quantity, unit_cost=cost,
                                   line_total=line_total, serials=serials or None))
    po.total = total


def create(db: Session, data: PurchaseOrderIn, user: User, at: datetime | None = None,
           require_supplier: bool = True) -> ImportReceipt:
    at = at or now()
    sup = _active_supplier(db, data.supplier_id) if (require_supplier or data.supplier_id) else None
    po = ImportReceipt(code=next_code(db, ImportReceipt, "PN", at), supplier_id=sup.id if sup else None,
                       supplier=sup.name if sup else (data.supplier_name or None), note=data.note,
                       user_id=user.id, created_at=at, status="draft")
    db.add(po)
    _fill_items(db, po, data, user, {})
    db.flush()
    if data.confirm:
        if user.role == "staff":
            raise BusinessError("Nhân viên chỉ lập phiếu nháp, chủ cửa hàng xác nhận nhập kho")
        confirm(db, po, user, at)
    return po


def update_draft(db: Session, po: ImportReceipt, data: PurchaseOrderIn, user: User) -> ImportReceipt:
    if po.status != "draft":
        raise BusinessError("Chỉ sửa được phiếu nhập đang ở trạng thái nháp")
    if user.role == "staff" and po.user_id != user.id:
        raise BusinessError("Nhân viên chỉ sửa được phiếu nháp do mình lập")
    sup = _active_supplier(db, data.supplier_id)
    keep_cost = {it.product_id: it.unit_cost for it in po.items}
    po.items.clear()
    db.flush()
    po.supplier_id, po.supplier, po.note = sup.id, sup.name, data.note
    _fill_items(db, po, data, user, keep_cost)
    db.flush()
    if data.confirm:
        if user.role == "staff":
            raise BusinessError("Nhân viên chỉ lập phiếu nháp, chủ cửa hàng xác nhận nhập kho")
        confirm(db, po, user)
    return po


def confirm(db: Session, po: ImportReceipt, user: User, at: datetime | None = None) -> ImportReceipt:
    """FR-PUR-04, 05: cộng tồn, ghi thẻ kho, cập nhật giá vốn bình quân, tạo serial; tất cả trong một giao dịch."""
    if po.status != "draft":
        raise BusinessError("Phiếu nhập đã được xác nhận hoặc đã hủy")
    if po.supplier_id:
        _active_supplier(db, po.supplier_id)
    at = at or now()
    products = _lock_products(db, [it.product_id for it in po.items])
    all_serials = [s for it in po.items for s in (it.serials or [])]
    if all_serials:
        exists = db.scalars(select(ProductSerial.serial_no).where(ProductSerial.serial_no.in_(all_serials))).all()
        if exists:
            raise BusinessError(f"Serial đã có trong hệ thống: {', '.join(sorted(exists))}", "DUPLICATE_SERIAL",
                                details={"serials": sorted(exists)})  # FR-PUR-03
    for it in po.items:
        p = products[it.product_id]
        if it.unit_cost <= 0:
            raise BusinessError(f"Dòng '{p.name}' chưa có giá nhập")
        if p.track_serial and len(it.serials or []) != it.quantity:
            raise BusinessError(f"'{p.name}' quản lý theo serial: cần nhập đủ {it.quantity} serial "
                                f"(đang có {len(it.serials or [])})")
        # BR-19: giá vốn bình quân gia quyền, làm tròn đến đồng
        old_qty = max(p.stock, 0)
        p.cost_price = round((old_qty * p.cost_price + it.quantity * it.unit_cost) / (old_qty + it.quantity))
        change_stock(db, p, it.quantity, "import", po.code, user, at=at)
        for s in it.serials or []:
            db.add(ProductSerial(product_id=p.id, serial_no=s, status="in_stock", purchase_item_id=it.id))
        it.line_total = it.quantity * it.unit_cost
    po.total = sum(it.line_total for it in po.items)
    po.status = "confirmed"
    po.received_at = at
    db.flush()
    audit.log(db, user, "PURCHASE_CONFIRM", "import_receipts", po.id, new={"code": po.code, "total": po.total})
    return po


def cancel(db: Session, po: ImportReceipt, reason: str, user: User) -> ImportReceipt:
    """Hủy phiếu nháp: chỉ đổi trạng thái. Hủy phiếu đã xác nhận (FR-PUR-06, BR-22): tồn hiện tại của mọi dòng
    phải đủ để trừ lại và không serial nào của phiếu đã bán; giá vốn bình quân được tính ngược lại."""
    if po.status == "cancelled":
        raise BusinessError("Phiếu nhập đã bị hủy trước đó")
    if po.status == "confirmed":
        products = _lock_products(db, [it.product_id for it in po.items])
        for it in po.items:
            p = products[it.product_id]
            if p.stock < it.quantity:
                raise BusinessError(f"Không thể hủy: '{p.name}' chỉ còn {p.stock}, phiếu đã nhập {it.quantity}")
            sold = db.scalar(select(func.count(ProductSerial.id)).where(
                ProductSerial.purchase_item_id == it.id, ProductSerial.status != "in_stock"))
            if sold:
                raise BusinessError(f"Không thể hủy: {sold} máy '{p.name}' của phiếu này đã bán hoặc đang xử lý")
        for it in po.items:
            p = products[it.product_id]
            remain = p.stock - it.quantity
            if remain > 0:
                p.cost_price = max(0, round((p.stock * p.cost_price - it.quantity * it.unit_cost) / remain))
            change_stock(db, p, -it.quantity, "import_cancel", po.code, user, note=reason)
            db.query(ProductSerial).filter(ProductSerial.purchase_item_id == it.id).delete()
        audit.log(db, user, "PURCHASE_CANCEL", "import_receipts", po.id,
                  old={"status": "confirmed", "total": po.total}, new={"status": "cancelled", "reason": reason})
    po.status = "cancelled"
    po.cancelled_at = now()
    po.cancel_reason = reason
    db.flush()
    return po
