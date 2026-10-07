"""Test thanh toán (tiền mặt / chuyển khoản / quẹt thẻ / VietQR), quét mã sản phẩm, tem QR và ảnh sản phẩm."""
import io

import pytest
from PIL import Image
from sqlalchemy import inspect, text
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.database import Base, ensure_schema, make_engine
from app.services.qr import clean_transfer_content, crc16_ccitt, vietqr_payload
from tests.helpers import product_id


def sell(client, h, **extra):
    pk1 = product_id(client, h, "PK001")
    return client.post("/api/invoices", json={"items": [{"product_id": pk1, "quantity": 1}], **extra}, headers=h)


# ---------------- Phương thức thanh toán ----------------
# TC-SAL-06 (SRS 11.3)
def test_cash_payment_records_change(client, staff_h):
    r = sell(client, staff_h, payment_method="cash", cash_received=500_000)
    assert r.status_code == 201, r.text
    inv = r.json()
    assert inv["cash_received"] == 500_000
    assert inv["change"] == 150_000


def test_cash_less_than_total_rejected(client, staff_h):
    r = sell(client, staff_h, payment_method="cash", cash_received=300_000)
    assert r.status_code == 422
    assert "ít hơn" in r.json()["detail"]
    items = client.get("/api/products", params={"q": "PK001"}, headers=staff_h).json()["items"]
    assert items[0]["stock"] == 12  # rollback, không trừ kho


@pytest.mark.parametrize("method,ref", [("card", "POS123456"), ("transfer", "TECHSTOREAI 2609231200"), ("qr", "TECHSTOREAI 2609231201")])
def test_non_cash_methods_store_reference(client, staff_h, method, ref):
    inv = sell(client, staff_h, payment_method=method, payment_ref=ref, cash_received=999_999).json()
    assert inv["payment_method"] == ("card" if method == "card" else "bank_transfer")  # transfer, qr: tên cũ
    assert inv["payment_ref"] == ref
    assert inv["cash_received"] is None  # tiền khách đưa chỉ áp dụng cho tiền mặt


def test_unknown_payment_method_rejected(client, staff_h):
    assert sell(client, staff_h, payment_method="bitcoin").status_code == 422


# ---------------- VietQR ----------------
# TC-PAY-01 (SRS 11.3)
def test_crc16_ccitt_known_vector():
    assert crc16_ccitt("123456789") == "29B1"


# TC-PAY-01 (SRS 11.3)
def test_vietqr_payload_structure():
    payload = vietqr_payload("970436", "0123456789", 350000, "TECHSTOREAI HD001")
    assert payload.startswith("000201010212")           # phiên bản + QR động (có số tiền)
    assert "0006970436" in payload and "01100123456789" in payload
    assert "5303704" in payload and "5406350000" in payload and "5802VN" in payload
    assert "0817TECHSTOREAI HD001" in payload
    assert payload[-8:-4] == "6304" and payload[-4:] == crc16_ccitt(payload[:-4])


def test_transfer_content_is_ascii_and_short():
    assert clean_transfer_content("Thanh toán đơn #HĐ-001 cho khách hàng thân thiết") == "Thanh toan don HD001 cho"


def test_vietqr_endpoint(client, staff_h):
    r = client.post("/api/payments/vietqr", json={"amount": 350000, "content": "TECHSTOREAI 1"}, headers=staff_h)
    assert r.status_code == 200
    body = r.json()
    assert body["svg"].startswith("<svg") and "width=" not in body["svg"].split(">")[0]
    assert body["amount"] == 350000 and body["account_no"] == settings.VIETQR_ACCOUNT_NO
    assert client.post("/api/payments/vietqr", json={"amount": 0}, headers=staff_h).status_code == 422


# ---------------- Quét mã & tem QR ----------------
# FR-SAL-01
def test_lookup_by_code_is_case_insensitive(client, staff_h):
    r = client.get("/api/products/by-code/ pk001 ", headers=staff_h)
    assert r.status_code == 200 and r.json()["code"] == "PK001"
    assert client.get("/api/products/by-code/XX999", headers=staff_h).status_code == 404


def test_qr_labels(client, owner_h, staff_h):
    labels = client.get("/api/products/qr-labels", headers=owner_h).json()
    assert [l["code"] for l in labels] == ["PK001", "PK002", "PK003"]
    assert all(l["svg"].startswith("<svg") for l in labels)
    pk3 = product_id(client, owner_h, "PK003")
    assert [l["code"] for l in client.get("/api/products/qr-labels", params={"ids": pk3}, headers=owner_h).json()] == ["PK003"]
    assert client.get("/api/products/qr-labels", headers=staff_h).status_code == 403


# ---------------- Ảnh sản phẩm ----------------
@pytest.fixture
def upload_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "UPLOAD_DIR", tmp_path)
    return tmp_path / "products"


def png_bytes(size=(1200, 900)):
    buf = io.BytesIO()
    Image.new("RGB", size, (37, 99, 235)).save(buf, "PNG")
    return buf.getvalue()


def test_upload_image_resizes_and_converts(client, owner_h, upload_dir):
    pk1 = product_id(client, owner_h, "PK001")
    r = client.post(f"/api/products/{pk1}/image", files={"file": ("a.png", png_bytes(), "image/png")}, headers=owner_h)
    assert r.status_code == 200, r.text
    url = r.json()["image_url"]
    assert url.startswith("/uploads/products/") and url.endswith(".webp")
    saved = upload_dir / url.rsplit("/", 1)[1]
    with Image.open(saved) as img:
        assert img.format == "WEBP" and max(img.size) == 800


def test_replacing_image_deletes_old_file(client, owner_h, upload_dir):
    pk1 = product_id(client, owner_h, "PK001")
    first = client.post(f"/api/products/{pk1}/image", files={"file": ("a.png", png_bytes(), "image/png")}, headers=owner_h).json()
    client.post(f"/api/products/{pk1}/image", files={"file": ("b.png", png_bytes((300, 300)), "image/png")}, headers=owner_h)
    assert not (upload_dir / first["image_url"].rsplit("/", 1)[1]).exists()
    assert len(list(upload_dir.iterdir())) == 1


def test_delete_image(client, owner_h, upload_dir):
    pk1 = product_id(client, owner_h, "PK001")
    client.post(f"/api/products/{pk1}/image", files={"file": ("a.png", png_bytes(), "image/png")}, headers=owner_h)
    r = client.delete(f"/api/products/{pk1}/image", headers=owner_h)
    assert r.json()["image_url"] is None
    assert list(upload_dir.iterdir()) == []


def test_reject_non_image_upload(client, owner_h, upload_dir):
    pk1 = product_id(client, owner_h, "PK001")
    fake = b"<svg onload='alert(1)'></svg>"
    r = client.post(f"/api/products/{pk1}/image", files={"file": ("x.png", fake, "image/png")}, headers=owner_h)
    assert r.status_code == 400


def test_staff_cannot_upload_image(client, staff_h, upload_dir):
    pk1 = product_id(client, staff_h, "PK001")
    r = client.post(f"/api/products/{pk1}/image", files={"file": ("a.png", png_bytes(), "image/png")}, headers=staff_h)
    assert r.status_code == 403


# ---------------- Nâng cấp CSDL cũ ----------------
def test_ensure_schema_adds_missing_columns():
    engine = make_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with engine.begin() as conn:  # giả lập CSDL phiên bản cũ chưa có các cột mới
        conn.execute(text("ALTER TABLE products DROP COLUMN image_url"))
        conn.execute(text("ALTER TABLE invoices DROP COLUMN payment_ref"))
    ensure_schema(engine)
    insp = inspect(engine)
    assert "image_url" in {c["name"] for c in insp.get_columns("products")}
    assert "payment_ref" in {c["name"] for c in insp.get_columns("invoices")}
    ensure_schema(engine)  # chạy lại không lỗi
