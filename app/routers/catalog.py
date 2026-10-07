import io
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from PIL import Image, ImageOps
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.database import get_db
from app.ai.service import strip_accents
from app.models import Category, ImportItem, InvoiceItem, Product, ProductSerial, StockMovement, User
from app.schemas import (CategoryIn, CategoryOut, ProductIn, ProductOut, ProductUpdate, SerialUpdateIn,
                         StockAdjustIn)
from app.security import ALL_STAFF, ANY_ROLE, MANAGERS
from app.services import app_settings, audit
from app.services.inventory import BusinessError, adjust_stock, change_stock
from app.services.purchasing import clean_serial
from app.services.qr import qr_svg

router = APIRouter(prefix="/api", tags=["catalog"])


# ---------------- Danh mục ----------------
@router.get("/categories", response_model=list[CategoryOut])
def list_categories(active_only: bool = False, db: Session = Depends(get_db), _: User = Depends(ALL_STAFF)):
    stmt = select(Category).order_by(Category.name)
    if active_only:
        stmt = stmt.where(Category.is_active.is_(True))
    return db.scalars(stmt).all()


def _category_values(db: Session, data: CategoryIn) -> dict:
    values = data.model_dump()
    defaults = app_settings.get_many(db, ["vat_rate_default", "warranty_months_default"])
    if values["default_vat_rate"] is None:
        values["default_vat_rate"] = defaults["vat_rate_default"]
    if values["default_warranty_months"] is None:
        values["default_warranty_months"] = defaults["warranty_months_default"]
    return values


@router.post("/categories", response_model=CategoryOut, status_code=201)
def create_category(data: CategoryIn, db: Session = Depends(get_db), _: User = Depends(MANAGERS)):
    cat = Category(**_category_values(db, data))
    db.add(cat)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(400, "Tên nhóm hàng đã tồn tại")
    return cat


@router.put("/categories/{cat_id}", response_model=CategoryOut)
def update_category(cat_id: int, data: CategoryIn, db: Session = Depends(get_db), _: User = Depends(MANAGERS)):
    cat = db.get(Category, cat_id)
    if cat is None:
        raise HTTPException(404, "Không tìm thấy nhóm hàng")
    for k, v in _category_values(db, data).items():
        setattr(cat, k, v)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(400, "Tên nhóm hàng đã tồn tại")
    return cat


@router.delete("/categories/{cat_id}")
def delete_category(cat_id: int, db: Session = Depends(get_db), _: User = Depends(MANAGERS)):
    """FR-CAT-03: nhóm đã có sản phẩm thì không xóa được, chỉ ẩn."""
    cat = db.get(Category, cat_id)
    if cat is None:
        raise HTTPException(404, "Không tìm thấy nhóm hàng")
    if db.scalar(select(func.count(Product.id)).where(Product.category_id == cat_id)):
        raise HTTPException(400, "Nhóm hàng đang có sản phẩm, không thể xóa. Hãy ẩn nhóm hàng thay vì xóa")
    db.delete(cat)
    db.commit()
    return {"ok": True}


@router.get("/catalog/names")
def english_names(db: Session = Depends(get_db), _: User = Depends(ANY_ROLE)) -> dict[str, str]:
    """Bảng tên tiếng Việt -> tiếng Anh của sản phẩm và nhóm hàng có name_en: giao diện tiếng Anh dùng để hiển thị tên
    ở mọi trang (kể cả hóa đơn cũ lưu tên lúc bán) mà không phải sửa từng API."""
    rows = db.execute(select(Category.name, Category.name_en).where(Category.name_en.is_not(None))).all()
    rows += db.execute(select(Product.name, Product.name_en).where(Product.name_en.is_not(None))).all()
    return {vi: en for vi, en in rows if en and en.strip()}


# ---------------- Sản phẩm ----------------
def stock_state(p: Product, threshold: int | None = None) -> str:
    """FR-PRD-07: Hết hàng khi tồn bằng 0, Sắp hết hàng khi tồn nhỏ hơn ngưỡng của sản phẩm (mặc định 5)."""
    if p.stock <= 0:
        return "out"
    return "low" if p.stock < (p.min_stock if threshold is None else threshold) else "in"


def product_out(p: Product, user: User) -> dict:
    data = ProductOut.model_validate(p).model_dump()
    data["category_name"] = p.category.name if p.category else None
    data["stock_state"] = stock_state(p)
    if user.role == "staff":
        data.pop("cost_price", None)  # nhân viên bán hàng không thấy trường giá nhập (FR-PRD-08, TC-AUT-02)
    return data


def _matches(p: Product, words: list[str]) -> bool:
    hay = strip_accents(f"{p.code} {p.barcode or ''} {p.name} {p.name_en or ''} {p.brand or ''}")
    return all(w in hay for w in words)


@router.get("/products")
def list_products(
    q: str | None = None, category_id: int | None = None,
    status: str | None = Query(None, pattern="^(active|inactive|discontinued)$"),
    stock: str | None = Query(None, pattern="^(in|out|low)$"),
    min_price: int | None = Query(None, ge=0), max_price: int | None = Query(None, ge=0),
    track_serial: bool | None = None,
    page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db), user: User = Depends(ALL_STAFF),
):
    """FR-PRD-06: tìm theo SKU, mã vạch, tên không phân biệt dấu; lọc nhóm, khoảng giá, trạng thái, tình trạng tồn."""
    stmt = select(Product).options(joinedload(Product.category))
    if category_id:
        stmt = stmt.where(Product.category_id == category_id)
    if status:
        stmt = stmt.where(Product.status == status)
    if stock == "in":
        stmt = stmt.where(Product.stock > 0)
    elif stock == "out":
        stmt = stmt.where(Product.stock <= 0)
    elif stock == "low":
        stmt = stmt.where(Product.stock < Product.min_stock)
    if min_price is not None:
        stmt = stmt.where(Product.sale_price >= min_price)
    if max_price is not None:
        stmt = stmt.where(Product.sale_price <= max_price)
    if track_serial is not None:
        stmt = stmt.where(Product.track_serial.is_(track_serial))
    stmt = stmt.order_by(Product.code)
    if q and q.strip():
        # Lọc bằng Python vì LIKE của SQLite không bỏ dấu tiếng Việt ("tai nghe" phải khớp "Tai nghe", "tai nghé")
        words = strip_accents(q).split()
        rows = [p for p in db.scalars(stmt).unique() if _matches(p, words)]
        total = len(rows)
        rows = rows[(page - 1) * size: page * size]
    else:
        total = db.scalar(select(func.count()).select_from(stmt.subquery()))
        rows = db.scalars(stmt.offset((page - 1) * size).limit(size)).unique().all()
    return {"items": [product_out(p, user) for p in rows], "total": total, "page": page, "size": size}


@router.get("/products/by-code/{code}")
def get_product_by_code(code: str, db: Session = Depends(get_db), user: User = Depends(ALL_STAFF)):
    """Tra sản phẩm theo SKU, mã vạch hoặc serial, dùng khi quét mã ở màn hình bán hàng (FR-SAL-01)."""
    key = code.strip()
    p = db.scalar(select(Product).where(func.upper(Product.code) == key.upper())) \
        or db.scalar(select(Product).where(Product.barcode == key))
    serial = None
    if p is None:
        serial = db.scalar(select(ProductSerial).where(ProductSerial.serial_no == key.upper()))
        p = serial.product if serial else None
    if p is None:
        raise HTTPException(404, f"Không tìm thấy sản phẩm có mã '{key}'")
    out = product_out(p, user)
    if serial is not None:
        out["serial"] = {"id": serial.id, "serial_no": serial.serial_no, "status": serial.status}
    return out


@router.get("/products/barcode/{code}")
def get_product_by_barcode(code: str, db: Session = Depends(get_db), user: User = Depends(ALL_STAFF)):
    return get_product_by_code(code, db, user)


@router.get("/products/qr-labels")
def product_qr_labels(ids: str | None = None, db: Session = Depends(get_db), _: User = Depends(MANAGERS)):
    """Tem QR để in dán lên sản phẩm. Mã QR chứa đúng mã sản phẩm (VD: PK001)."""
    stmt = select(Product).where(Product.status == "active").order_by(Product.code)
    if ids:
        try:
            id_list = [int(x) for x in ids.split(",") if x.strip()]
        except ValueError:
            raise HTTPException(400, "Danh sách id không hợp lệ")
        stmt = stmt.where(Product.id.in_(id_list))
    return [{"id": p.id, "code": p.code, "name": p.name, "price": p.sale_price, "svg": qr_svg(p.code)}
            for p in db.scalars(stmt)]


@router.get("/products/{product_id}")
def get_product(product_id: int, db: Session = Depends(get_db), user: User = Depends(ALL_STAFF)):
    p = db.get(Product, product_id)
    if p is None:
        raise HTTPException(404, "Không tìm thấy sản phẩm")
    return product_out(p, user)


def _category_id_by_name(db: Session, name: str) -> int | None:
    """Tìm nhóm hàng theo tên (không phân biệt hoa thường, khoảng trắng thừa), chưa có thì tạo mới.
    So khớp bằng Python vì lower() của SQLite không xử lý chữ có dấu tiếng Việt."""
    name = " ".join(name.split())
    if not name:
        return None
    cat = next((c for c in db.scalars(select(Category)) if c.name.casefold() == name.casefold()), None)
    if cat is None:
        cat = Category(name=name)
        db.add(cat)
        db.flush()
    return cat.id


def _apply_category_defaults(db: Session, fields: dict) -> None:
    cat = db.get(Category, fields["category_id"]) if fields.get("category_id") else None
    defaults = app_settings.get_many(db, ["vat_rate_default", "warranty_months_default"])
    if fields.get("vat_rate") is None:
        fields["vat_rate"] = cat.default_vat_rate if cat else defaults["vat_rate_default"]  # BR-04
    if fields.get("warranty_months") is None:
        fields["warranty_months"] = cat.default_warranty_months if cat else defaults["warranty_months_default"]


@router.post("/products", status_code=201)
def create_product(data: ProductIn, db: Session = Depends(get_db), user: User = Depends(MANAGERS)):
    fields = data.model_dump(exclude={"stock", "category_name"})
    if data.category_name is not None:
        fields["category_id"] = _category_id_by_name(db, data.category_name)
    elif data.category_id and db.get(Category, data.category_id) is None:
        raise HTTPException(400, "Nhóm hàng không tồn tại")
    if data.track_serial and data.stock:
        raise HTTPException(400, "Sản phẩm quản lý theo serial: tồn kho được tạo khi nhập hàng kèm serial")
    _apply_category_defaults(db, fields)
    initial_stock = data.stock
    p = Product(**fields, stock=0)
    db.add(p)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(400, "Mã sản phẩm hoặc mã vạch đã tồn tại")
    if initial_stock:
        change_stock(db, p, initial_stock, "adjust", None, user, note="Tồn kho đầu kỳ")
    db.commit()
    db.refresh(p)
    return product_out(p, user)


@router.put("/products/{product_id}")
def update_product(product_id: int, data: ProductUpdate, db: Session = Depends(get_db),
                   user: User = Depends(MANAGERS)):
    p = db.get(Product, product_id)
    if p is None:
        raise HTTPException(404, "Không tìm thấy sản phẩm")
    changes = data.model_dump(exclude_unset=True)
    if "category_name" in changes:
        changes["category_id"] = _category_id_by_name(db, changes.pop("category_name") or "")
    elif changes.get("category_id") and db.get(Category, changes["category_id"]) is None:
        raise HTTPException(400, "Nhóm hàng không tồn tại")
    if "track_serial" in changes and changes["track_serial"] != p.track_serial:
        in_stock = db.scalar(select(func.count(ProductSerial.id)).where(
            ProductSerial.product_id == p.id, ProductSerial.status == "in_stock"))
        if p.stock != (in_stock if changes["track_serial"] else 0):
            raise HTTPException(400, "Chỉ đổi cách quản lý serial khi tồn kho bằng 0 (hoặc khớp số serial còn trong kho)")
    for key in ("vat_rate", "warranty_months"):
        if key in changes and changes[key] is None:
            changes.pop(key)
    old_prices = {"sale_price": p.sale_price, "cost_price": p.cost_price}
    for k, v in changes.items():
        setattr(p, k, v)
    new_prices = {"sale_price": p.sale_price, "cost_price": p.cost_price}
    if old_prices != new_prices:  # FR-PRD-05
        audit.log(db, user, "PRICE_CHANGE", "products", p.id, old=old_prices, new=new_prices)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(400, "Mã sản phẩm hoặc mã vạch đã tồn tại")
    return product_out(p, user)


@router.delete("/products/{product_id}")
def delete_product(product_id: int, db: Session = Depends(get_db), _: User = Depends(MANAGERS)):
    p = db.get(Product, product_id)
    if p is None:
        raise HTTPException(404, "Không tìm thấy sản phẩm")
    if (db.scalar(select(func.count(InvoiceItem.id)).where(InvoiceItem.product_id == product_id))
            or db.scalar(select(func.count(ImportItem.id)).where(ImportItem.product_id == product_id))):
        # Đã có trong hóa đơn hoặc phiếu nhập: chỉ ngừng kinh doanh để giữ lịch sử chứng từ
        p.status = "inactive"
        db.commit()
        return {"ok": True, "message": "Sản phẩm đã có trong hóa đơn hoặc phiếu nhập nên không thể xóa, "
                                       "đã chuyển sang ngừng kinh doanh"}
    db.query(StockMovement).filter(StockMovement.product_id == product_id).delete()
    _remove_upload(p.image_url)
    db.delete(p)
    db.commit()
    return {"ok": True, "message": "Đã xóa sản phẩm"}


@router.post("/products/{product_id}/adjust-stock")
def adjust_product_stock(product_id: int, data: StockAdjustIn, db: Session = Depends(get_db),
                         user: User = Depends(MANAGERS)):
    p = db.get(Product, product_id)
    if p is None:
        raise HTTPException(404, "Không tìm thấy sản phẩm")
    try:
        adjust_stock(db, p, data.new_stock, data.note, user)
    except BusinessError as e:
        db.rollback()
        raise e.http()
    db.commit()
    return product_out(p, user)


@router.get("/stock-movements")
def list_movements(product_id: int | None = None, type: str | None = None,
                   date_from: str | None = None, date_to: str | None = None,
                   page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=200),
                   db: Session = Depends(get_db), _: User = Depends(ALL_STAFF)):
    """FR-STK-05: thẻ kho theo sản phẩm và khoảng ngày (nhân viên được xem, bảng 4.2)."""
    from app.services.reports import parse_range
    stmt = select(StockMovement).options(joinedload(StockMovement.product))
    if product_id:
        stmt = stmt.where(StockMovement.product_id == product_id)
    if type:
        stmt = stmt.where(StockMovement.type == type)
    if date_from or date_to:
        start, end = parse_range(date_from, date_to)
        stmt = stmt.where(StockMovement.created_at >= start, StockMovement.created_at < end)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(StockMovement.id.desc()).offset((page - 1) * size).limit(size)).all()
    return {"total": total, "items": [{
        "id": m.id, "product_code": m.product.code, "product_name": m.product.name, "change": m.change,
        "stock_before": m.stock_after - m.change, "stock_after": m.stock_after, "type": m.type,
        "ref_code": m.ref_code, "note": m.note, "created_at": m.created_at,
    } for m in rows]}


# ---------------- Serial / IMEI (UC-12) ----------------
def serial_out(s: ProductSerial) -> dict:
    return {"id": s.id, "product_id": s.product_id, "product_code": s.product.code, "product_name": s.product.name,
            "serial_no": s.serial_no, "status": s.status, "invoice_item_id": s.invoice_item_id,
            "purchase_item_id": s.purchase_item_id, "created_at": s.created_at}


@router.get("/products/{product_id}/serials")
def list_product_serials(product_id: int, status: str | None = None, db: Session = Depends(get_db),
                         _: User = Depends(ALL_STAFF)):
    stmt = select(ProductSerial).options(joinedload(ProductSerial.product)).where(ProductSerial.product_id == product_id)
    if status:
        stmt = stmt.where(ProductSerial.status == status)
    return [serial_out(s) for s in db.scalars(stmt.order_by(ProductSerial.serial_no))]


@router.get("/serials")
def search_serials(q: str = Query(min_length=2), db: Session = Depends(get_db), _: User = Depends(ALL_STAFF)):
    like = f"%{q.strip().upper()}%"
    rows = db.scalars(select(ProductSerial).options(joinedload(ProductSerial.product))
                      .where(ProductSerial.serial_no.like(like)).order_by(ProductSerial.serial_no).limit(50))
    return [serial_out(s) for s in rows]


@router.put("/serials/{serial_id}")
def update_serial(serial_id: int, data: SerialUpdateIn, db: Session = Depends(get_db), user: User = Depends(MANAGERS)):
    """Sửa serial nhập nhầm, hoặc đánh dấu máy trong kho bị lỗi (defective) và ngược lại. Tồn kho đi theo serial."""
    s = db.get(ProductSerial, serial_id)
    if s is None:
        raise HTTPException(404, "Không tìm thấy serial")
    try:
        if data.serial_no:
            new_no = clean_serial(data.serial_no)
            if new_no != s.serial_no:
                if s.status != "in_stock":
                    raise BusinessError("Chỉ sửa số serial của máy còn trong kho")
                if db.scalar(select(ProductSerial.id).where(ProductSerial.serial_no == new_no)):
                    raise BusinessError(f"Serial {new_no} đã tồn tại")
                audit.log(db, user, "SERIAL_UPDATE", "product_serials", s.id, old=s.serial_no, new=new_no)
                s.serial_no = new_no
        if data.status and data.status != s.status:
            if s.status not in ("in_stock", "defective", "returned"):
                raise BusinessError("Chỉ đổi trạng thái máy đang trong kho, lỗi hoặc khách trả")
            note = data.note or f"Serial {s.serial_no}: {s.status} -> {data.status}"
            if data.status == "in_stock":
                change_stock(db, s.product, 1, "adjust", None, user, note=note)
            elif s.status == "in_stock":
                change_stock(db, s.product, -1, "adjust", None, user, note=note)
            audit.log(db, user, "STOCK_ADJUST", "product_serials", s.id, old=s.status, new=data.status)
            s.status = data.status
        db.commit()
    except BusinessError as e:
        db.rollback()
        raise e.http()
    return serial_out(s)


# ---------------- Ảnh sản phẩm ----------------
MAX_IMAGE_BYTES = 5 * 1024 * 1024
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "GIF"}
Image.MAX_IMAGE_PIXELS = 40_000_000  # chặn ảnh "bom giải nén"


def _upload_dir() -> Path:
    path = settings.UPLOAD_DIR / "products"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _remove_upload(url: str | None) -> None:
    """Chỉ xóa ảnh do người dùng tải lên (/uploads/...), không xóa ảnh mẫu trong /static."""
    if url and url.startswith("/uploads/products/"):
        (_upload_dir() / Path(url).name).unlink(missing_ok=True)


@router.post("/products/{product_id}/image")
def upload_product_image(product_id: int, file: UploadFile = File(...), db: Session = Depends(get_db),
                         user: User = Depends(MANAGERS)):
    p = db.get(Product, product_id)
    if p is None:
        raise HTTPException(404, "Không tìm thấy sản phẩm")
    raw = file.file.read(MAX_IMAGE_BYTES + 1)
    if len(raw) > MAX_IMAGE_BYTES:
        raise HTTPException(400, "Ảnh vượt quá 5 MB")
    try:
        with Image.open(io.BytesIO(raw)) as probe:
            probe.verify()
        img = Image.open(io.BytesIO(raw))
        if img.format not in ALLOWED_FORMATS:
            raise ValueError
        img = ImageOps.exif_transpose(img)
        img.thumbnail((800, 800))
        img = img.convert("RGBA" if img.mode in ("RGBA", "LA", "P") else "RGB")
    except Exception:
        raise HTTPException(400, "File không phải ảnh hợp lệ (chấp nhận JPG, PNG, WEBP, GIF)")
    # Lưu lại dưới dạng WEBP: đồng nhất định dạng, nhẹ, loại bỏ metadata/EXIF của file gốc
    name = f"{uuid.uuid4().hex}.webp"
    img.save(_upload_dir() / name, "WEBP", quality=85)
    _remove_upload(p.image_url)
    p.image_url = f"/uploads/products/{name}"
    db.commit()
    return product_out(p, user)


@router.delete("/products/{product_id}/image")
def delete_product_image(product_id: int, db: Session = Depends(get_db), user: User = Depends(MANAGERS)):
    p = db.get(Product, product_id)
    if p is None:
        raise HTTPException(404, "Không tìm thấy sản phẩm")
    _remove_upload(p.image_url)
    p.image_url = None
    db.commit()
    return product_out(p, user)
