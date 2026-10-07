"""Test sản phẩm: nhập tên nhóm hàng tự do khi tạo / sửa sản phẩm."""
from tests.helpers import product_id


def categories(client, h):
    return {c["name"]: c["id"] for c in client.get("/api/categories", headers=h).json()}


def new_product(**kw):
    return {"code": "NEW01", "name": "Cáp sạc USB-C", "sale_price": 90_000, **kw}


# FR-PRD-01
def test_create_product_with_new_category_name(client, owner_h):
    r = client.post("/api/products", json=new_product(category_name="  Cáp   sạc "), headers=owner_h)
    assert r.status_code == 201, r.text
    cats = categories(client, owner_h)
    assert "Cáp sạc" in cats
    assert r.json()["category_id"] == cats["Cáp sạc"]
    assert r.json()["category_name"] == "Cáp sạc"


def test_category_name_reuses_existing_ignoring_case(client, owner_h):
    before = categories(client, owner_h)
    r = client.post("/api/products", json=new_product(category_name="PHỤ KIỆN"), headers=owner_h)
    assert r.status_code == 201, r.text
    assert r.json()["category_id"] == before["Phụ kiện"]
    assert categories(client, owner_h) == before


def test_update_product_category_name(client, owner_h):
    pk1 = product_id(client, owner_h, "PK001")
    r = client.put(f"/api/products/{pk1}", json={"category_name": "Tai nghe"}, headers=owner_h)
    assert r.status_code == 200, r.text
    assert r.json()["category_name"] == "Tai nghe"
    r = client.put(f"/api/products/{pk1}", json={"category_name": ""}, headers=owner_h)
    assert r.json()["category_id"] is None


def test_failed_product_save_does_not_leave_new_category(client, owner_h):
    before = categories(client, owner_h)
    r = client.post("/api/products", json=new_product(code="PK001", category_name="Nhóm thừa"), headers=owner_h)
    assert r.status_code == 400
    assert categories(client, owner_h) == before


# FR-PRD-02
def test_sale_price_must_be_positive(client, owner_h):
    for price in (0, -1000):
        r = client.post("/api/products", json=new_product(sale_price=price), headers=owner_h)
        assert r.status_code == 422
        assert "Giá bán phải lớn hơn 0" in r.text
    pk1 = product_id(client, owner_h, "PK001")
    r = client.put(f"/api/products/{pk1}", json={"sale_price": 0}, headers=owner_h)
    assert r.status_code == 422
    assert "Giá bán phải lớn hơn 0" in r.text


def test_delete_product_without_transactions(client, owner_h):
    pid = client.post("/api/products", json=new_product(), headers=owner_h).json()["id"]
    r = client.delete(f"/api/products/{pid}", headers=owner_h)
    assert r.status_code == 200, r.text
    assert client.get(f"/api/products/{pid}", headers=owner_h).status_code == 404


# FR-PRD-04
def test_delete_product_with_invoice_or_import_only_deactivates(client, owner_h):
    """SRS UC003 A3: đã có trong hóa đơn hoặc phiếu nhập thì không xóa cứng, chuyển sang ngừng kinh doanh."""
    pk1 = product_id(client, owner_h, "PK001")
    pk3 = product_id(client, owner_h, "PK003")
    assert client.post("/api/invoices", json={"items": [{"product_id": pk1, "quantity": 1}]},
                       headers=owner_h).status_code == 201
    assert client.post("/api/imports", json={"items": [{"product_id": pk3, "quantity": 5, "unit_cost": 90_000}]},
                       headers=owner_h).status_code == 201
    for pid in (pk1, pk3):
        r = client.delete(f"/api/products/{pid}", headers=owner_h)
        assert r.status_code == 200, r.text
        assert "ngừng kinh doanh" in r.json()["message"]
        assert client.get(f"/api/products/{pid}", headers=owner_h).json()["status"] == "inactive"
