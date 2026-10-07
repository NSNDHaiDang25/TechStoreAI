"""Nhập danh mục sản phẩm từ tệp CSV (SRS 7.7, bảng 8.5 POST /api/products/import, NFR-SEC-10).

Quy trình: tải mẫu CSV -> điền -> tải lên với dry_run=true để xem trước -> tải lên lần nữa để nhập thật.
Nhập theo kiểu "tất cả hoặc không": chỉ cần một dòng lỗi là không dòng nào được ghi, tránh nhập dở dang.
SKU đã có trong hệ thống được bỏ qua (sửa giá, thông tin ở màn hình Sản phẩm để có audit log đổi giá).
Tồn đầu kỳ không nhập ở đây mà bằng một phiếu nhập có nhà cung cấp "Tồn đầu kỳ" (SRS 7.7).
"""
import csv
import io
import re

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Category, Product, User
from app.routers.catalog import _apply_category_defaults
from app.schemas import ProductIn
from app.security import MANAGERS
from app.services import audit
from app.services.export import to_csv

router = APIRouter(prefix="/api", tags=["catalog"])

MAX_BYTES = 5 * 1024 * 1024  # NFR-SEC-10
MAX_ROWS = 5000
# Cột trong mẫu: (tên cột, tên trường, bắt buộc, ví dụ)
COLUMNS = [
    ("sku", "code", True, "TN-SONY-02"),
    ("ma_vach", "barcode", False, "8938505970012"),
    ("ten", "name", True, "Tai nghe Sony WH-1000XM5"),
    ("nhom_hang", "category_name", False, "Tai nghe"),
    ("hang", "brand", False, "Sony"),
    ("gia_ban", "sale_price", True, "8490000"),
    ("gia_von", "cost_price", False, "7200000"),
    ("vat", "vat_rate", False, "10"),
    ("bao_hanh_thang", "warranty_months", False, "12"),
    ("ton_toi_thieu", "min_stock", False, "3"),
    ("theo_serial", "track_serial", False, "1"),
    ("mo_ta", "description", False, "Chống ồn chủ động, pin 30 giờ"),
]
# Chấp nhận cả tên cột tiếng Việt có dấu / tiếng Anh thường gặp
ALIASES = {
    "sku": "code", "ma": "code", "ma_sp": "code", "mã": "code", "code": "code",
    "ma_vach": "barcode", "mã vạch": "barcode", "barcode": "barcode",
    "ten": "name", "tên": "name", "ten_san_pham": "name", "name": "name",
    "nhom_hang": "category_name", "nhóm": "category_name", "nhóm hàng": "category_name", "category": "category_name",
    "hang": "brand", "hãng": "brand", "brand": "brand",
    "gia_ban": "sale_price", "giá bán": "sale_price", "sale_price": "sale_price",
    "gia_von": "cost_price", "giá vốn": "cost_price", "gia_nhap": "cost_price", "cost_price": "cost_price",
    "vat": "vat_rate", "vat_rate": "vat_rate",
    "bao_hanh_thang": "warranty_months", "bảo hành": "warranty_months", "warranty_months": "warranty_months",
    "ton_toi_thieu": "min_stock", "tồn tối thiểu": "min_stock", "min_stock": "min_stock",
    "theo_serial": "track_serial", "serial": "track_serial", "track_serial": "track_serial",
    "mo_ta": "description", "mô tả": "description", "description": "description",
}
INT_FIELDS = {"sale_price", "cost_price", "vat_rate", "warranty_months", "min_stock"}


@router.get("/products/import-template")
def import_template(_: User = Depends(MANAGERS)):
    content = to_csv([c[0] for c in COLUMNS], [[c[3] for c in COLUMNS]])
    return Response(content, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="mau_nhap_san_pham.csv"'})


def _decode(data: bytes) -> str:
    if b"\x00" in data[:4096]:
        raise HTTPException(400, "Tệp không phải CSV dạng văn bản")  # kiểm tra loại tệp bằng nội dung
    for enc in ("utf-8-sig", "cp1258", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise HTTPException(400, "Không đọc được tệp. Hãy lưu CSV với mã hóa UTF-8")


def _number(raw: str) -> int | None:
    """'8.490.000', '8,490,000', '8490000 đ' -> 8490000; '1,5' -> 2 (làm tròn)."""
    s = re.sub(r"\s|₫|đ|vnd", "", raw.strip().lower())
    if not s:
        return None
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+", s):  # dấu phân cách hàng nghìn
        s = re.sub(r"[.,]", "", s)
    return int(round(float(s.replace(",", "."))))


def parse_rows(text: str) -> tuple[list[dict], list[dict]]:
    sample = text[:2048]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    rows = [r for r in reader if any(c.strip() for c in r)]
    if not rows:
        raise HTTPException(400, "Tệp rỗng")
    header = [ALIASES.get(h.strip().lower()) for h in rows[0]]
    if "code" not in header or "name" not in header or "sale_price" not in header:
        raise HTTPException(400, "Thiếu cột bắt buộc: sku, ten, gia_ban (tải tệp mẫu để xem đúng tên cột)")
    if len(rows) - 1 > MAX_ROWS:
        raise HTTPException(400, f"Tối đa {MAX_ROWS} dòng mỗi lần nhập")
    good, errors = [], []
    for line_no, r in enumerate(rows[1:], start=2):
        raw = {f: (r[i].strip() if i < len(r) else "") for i, f in enumerate(header) if f}
        try:
            fields: dict = {}
            for f, v in raw.items():
                if f in INT_FIELDS:
                    n = _number(v)
                    if n is not None:
                        fields[f] = n
                elif f == "track_serial":
                    fields[f] = v.lower() in ("1", "x", "co", "có", "yes", "true", "y")
                elif v:
                    fields[f] = v
            data = ProductIn(**fields)
        except (ValueError, ValidationError) as e:
            msg = "; ".join(str(x["msg"]).replace("Value error, ", "") for x in e.errors()) if isinstance(e, ValidationError) else "Số không hợp lệ"
            errors.append({"line": line_no, "sku": raw.get("code", ""), "error": msg})
            continue
        good.append({"line": line_no, "data": data})
    return good, errors


@router.post("/products/import")
async def import_products(file: UploadFile = File(...), dry_run: bool = Query(False),
                          db: Session = Depends(get_db), user: User = Depends(MANAGERS)):
    data = await file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(400, "Tệp quá 5 MB")
    good, errors = parse_rows(_decode(data))

    # Trùng SKU / mã vạch trong tệp và với dữ liệu đã có
    existing_codes = {c.upper() for c in db.scalars(select(Product.code))}
    existing_barcodes = {b for b in db.scalars(select(Product.barcode).where(Product.barcode.is_not(None)))}
    seen_codes, seen_barcodes, to_create, skipped = set(), set(), [], []
    for row in good:
        d = row["data"]
        if d.code.upper() in existing_codes:
            skipped.append({"line": row["line"], "sku": d.code, "reason": "SKU đã có, bỏ qua"})
        elif d.code.upper() in seen_codes:
            errors.append({"line": row["line"], "sku": d.code, "error": "SKU bị lặp trong tệp"})
        elif d.barcode and (d.barcode in existing_barcodes or d.barcode in seen_barcodes):
            errors.append({"line": row["line"], "sku": d.code, "error": f"Mã vạch {d.barcode} đã được dùng"})
        else:
            seen_codes.add(d.code.upper())
            if d.barcode:
                seen_barcodes.add(d.barcode)
            to_create.append(row)
    errors.sort(key=lambda e: e["line"])
    preview = [{"line": r["line"], "sku": r["data"].code, "name": r["data"].name, "category": r["data"].category_name,
                "sale_price": r["data"].sale_price, "track_serial": r["data"].track_serial} for r in to_create[:200]]
    result = {"dry_run": dry_run, "to_create": len(to_create), "skipped": skipped, "errors": errors, "preview": preview}
    if dry_run or errors:
        if errors and not dry_run:
            raise HTTPException(400, {"message": f"Tệp có {len(errors)} dòng lỗi, chưa nhập dòng nào", **result})
        return result

    categories = {c.name.strip().lower(): c for c in db.scalars(select(Category))}
    for row in to_create:
        d = row["data"]
        fields = d.model_dump(exclude={"stock", "category_name", "category_id"})
        name = (d.category_name or "").strip()
        if name:
            cat = categories.get(name.lower())
            if cat is None:
                cat = Category(name=name)
                db.add(cat)
                db.flush()
                categories[name.lower()] = cat
            fields["category_id"] = cat.id
        _apply_category_defaults(db, fields)
        db.add(Product(**fields, stock=0))
    db.flush()
    audit.log(db, user, "PRODUCT_IMPORT", "products", None,
              new={"file": file.filename, "created": len(to_create), "skipped": len(skipped)})
    db.commit()
    total = db.scalar(select(func.count(Product.id)))
    return {**result, "created": len(to_create), "product_count": total}
