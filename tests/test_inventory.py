"""Test tồn kho: nhập hàng, hủy hóa đơn, sửa hóa đơn, điều chỉnh kho, nhật ký nhập-xuất-tồn."""
from tests.helpers import product_id, stock_of


def sell(client, h, pid, qty, **extra):
    r = client.post("/api/invoices", json={"items": [{"product_id": pid, "quantity": qty}], **extra}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def sell_pending(client, h, pid, qty):
    """Hóa đơn chuyển khoản chờ xác nhận: còn sửa được (BR-24)."""
    inv = sell(client, h, pid, qty, payment_method="bank_transfer")
    assert inv["status"] == "pending_payment"
    return inv


def test_import_increases_stock_and_updates_cost(client, owner_h):
    pk1 = product_id(client, owner_h, "PK001")
    r = client.post("/api/imports", json={"supplier": "NCC A", "items": [
        {"product_id": pk1, "quantity": 8, "unit_cost": 230_000}]}, headers=owner_h)
    assert r.status_code == 201, r.text
    assert r.json()["total"] == 8 * 230_000
    p = client.get(f"/api/products/{pk1}", headers=owner_h).json()
    assert p["stock"] == 20
    assert p["cost_price"] == 224_000  # BR-19: (12 x 220.000 + 8 x 230.000) / 20


def test_import_can_create_new_products(client, owner_h):
    cat = client.get("/api/categories", headers=owner_h).json()[0]["id"]
    r = client.post("/api/imports", json={"supplier": "NCC mới", "items": [
        {"new_product": {"name": "  Loa   kéo di động K8 ", "category_id": cat, "sale_price": 1_500_000}, "quantity": 3, "unit_cost": 900_000},
        {"new_product": {"name": "loa kéo di động k8", "sale_price": 1_500_000}, "quantity": 2, "unit_cost": 900_000},
        {"new_product": {"name": "Micro không dây M2", "code": "mic01", "sale_price": 450_000}, "quantity": 5, "unit_cost": 250_000},
    ]}, headers=owner_h)
    assert r.status_code == 201, r.text
    assert r.json()["total"] == 5 * 900_000 + 5 * 250_000
    codes = [it["product_code"] for it in r.json()["items"]]
    assert codes == ["SP0001", "SP0001", "MIC01"]  # cùng tên mới ở 2 dòng => một sản phẩm
    loa = client.get("/api/products/by-code/SP0001", headers=owner_h).json()
    assert (loa["name"], loa["stock"], loa["cost_price"], loa["sale_price"], loa["category_id"]) == \
        ("Loa kéo di động K8", 5, 900_000, 1_500_000, cat)
    assert client.get("/api/products/by-code/MIC01", headers=owner_h).json()["stock"] == 5
    moves = client.get("/api/stock-movements", params={"type": "import"}, headers=owner_h).json()["items"]
    assert sum(m["change"] for m in moves if m["product_code"] == "SP0001") == 5


def test_import_new_product_rejects_duplicates_and_rolls_back(client, owner_h):
    dup_name = client.post("/api/imports", json={"items": [
        {"new_product": {"name": "tai nghe bluetooth a1", "sale_price": 1}, "quantity": 1, "unit_cost": 1}]}, headers=owner_h)
    assert dup_name.status_code == 409 and "đã có trong danh mục" in dup_name.json()["detail"]
    dup_code = client.post("/api/imports", json={"items": [
        {"new_product": {"name": "Hàng mới X", "code": "pk001", "sale_price": 1}, "quantity": 1, "unit_cost": 1}]}, headers=owner_h)
    assert dup_code.status_code == 409
    # dòng lỗi phía sau => sản phẩm mới ở dòng trước cũng không được tạo
    bad = client.post("/api/imports", json={"items": [
        {"new_product": {"name": "Hàng mới Y", "sale_price": 1}, "quantity": 1, "unit_cost": 1},
        {"product_id": 99999, "quantity": 1, "unit_cost": 1}]}, headers=owner_h)
    assert bad.status_code == 404
    assert client.get("/api/products", params={"q": "Hàng mới"}, headers=owner_h).json()["total"] == 0
    assert stock_of(client, owner_h, "PK001") == 12


def test_import_item_needs_exactly_one_product(client, owner_h):
    pk1 = product_id(client, owner_h, "PK001")
    for item in ({"quantity": 1, "unit_cost": 1},
                 {"product_id": pk1, "new_product": {"name": "X", "sale_price": 1}, "quantity": 1, "unit_cost": 1}):
        assert client.post("/api/imports", json={"items": [item]}, headers=owner_h).status_code == 422


def test_staff_cannot_import(client, staff_h):
    pk1 = product_id(client, staff_h, "PK001")
    r = client.post("/api/imports", json={"items": [{"product_id": pk1, "quantity": 1, "unit_cost": 1}]},
                    headers=staff_h)
    assert r.status_code == 403


def test_cancel_invoice_restores_stock(client, owner_h):
    pk1 = product_id(client, owner_h, "PK001")
    inv = sell(client, owner_h, pk1, 5)
    assert stock_of(client, owner_h, "PK001") == 7
    r = client.post(f"/api/invoices/{inv['id']}/cancel", json={"reason": "Khách trả hàng"}, headers=owner_h)
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"
    assert stock_of(client, owner_h, "PK001") == 12


def test_cancel_twice_does_not_double_restore(client, owner_h):
    pk1 = product_id(client, owner_h, "PK001")
    inv = sell(client, owner_h, pk1, 5)
    client.post(f"/api/invoices/{inv['id']}/cancel", json={"reason": "Lập sai hóa đơn"}, headers=owner_h)
    r = client.post(f"/api/invoices/{inv['id']}/cancel", json={"reason": "Lập sai hóa đơn"}, headers=owner_h)
    assert r.status_code == 409
    assert stock_of(client, owner_h, "PK001") == 12


def test_edit_invoice_adjusts_stock_by_difference(client, owner_h):
    pk1, pk3 = product_id(client, owner_h, "PK001"), product_id(client, owner_h, "PK003")
    inv = sell_pending(client, owner_h, pk1, 5)  # PK001: 12 -> 7
    r = client.put(f"/api/invoices/{inv['id']}", json={"items": [
        {"product_id": pk1, "quantity": 2}, {"product_id": pk3, "quantity": 3}], "payment_method": "bank_transfer"},
        headers=owner_h)
    assert r.status_code == 200, r.text
    assert r.json()["code"] == inv["code"] and r.json()["status"] == "pending_payment"
    assert r.json()["total"] == 2 * 350_000 + 3 * 190_000
    assert stock_of(client, owner_h, "PK001") == 10
    assert stock_of(client, owner_h, "PK003") == 47


def test_edit_invoice_can_reuse_its_own_stock(client, owner_h):
    """Hóa đơn đang giữ 12 cái (hết kho); sửa thành 12 cái vẫn hợp lệ vì hàng cũ được hoàn trước."""
    pk1 = product_id(client, owner_h, "PK001")
    inv = sell_pending(client, owner_h, pk1, 12)
    r = client.put(f"/api/invoices/{inv['id']}", json={"items": [{"product_id": pk1, "quantity": 12}],
                                                       "payment_method": "bank_transfer"}, headers=owner_h)
    assert r.status_code == 200
    assert stock_of(client, owner_h, "PK001") == 0


def test_failed_edit_rolls_back_stock(client, owner_h):
    pk1 = product_id(client, owner_h, "PK001")
    inv = sell_pending(client, owner_h, pk1, 5)  # còn 7
    r = client.put(f"/api/invoices/{inv['id']}", json={"items": [{"product_id": pk1, "quantity": 50}]},
                   headers=owner_h)
    assert r.status_code == 409
    assert stock_of(client, owner_h, "PK001") == 7
    detail = client.get(f"/api/invoices/{inv['id']}", headers=owner_h).json()
    assert detail["items"][0]["quantity"] == 5


def test_cannot_edit_cancelled_invoice(client, owner_h):
    pk1 = product_id(client, owner_h, "PK001")
    inv = sell(client, owner_h, pk1, 1)
    client.post(f"/api/invoices/{inv['id']}/cancel", json={"reason": "Lập sai hóa đơn"}, headers=owner_h)
    r = client.put(f"/api/invoices/{inv['id']}", json={"items": [{"product_id": pk1, "quantity": 1}]},
                   headers=owner_h)
    assert r.status_code == 409


def test_cannot_edit_paid_invoice(client, owner_h):
    """BR-24: hóa đơn đã thanh toán không sửa nội dung."""
    pk1 = product_id(client, owner_h, "PK001")
    inv = sell(client, owner_h, pk1, 1)
    r = client.put(f"/api/invoices/{inv['id']}", json={"items": [{"product_id": pk1, "quantity": 2}]},
                   headers=owner_h)
    assert r.status_code == 409 and "BR-24" in r.json()["detail"]


# TC-STK-02 (SRS 11.3)
def test_stock_movements_logged(client, owner_h):
    pk1 = product_id(client, owner_h, "PK001")
    inv = sell(client, owner_h, pk1, 3)
    client.post(f"/api/invoices/{inv['id']}/cancel", json={"reason": "Lập sai hóa đơn"}, headers=owner_h)
    moves = client.get("/api/stock-movements", params={"product_id": pk1}, headers=owner_h).json()["items"]
    assert [(m["type"], m["change"], m["stock_after"]) for m in moves] == [("cancel", 3, 12), ("sale", -3, 9)]


def test_adjust_stock(client, owner_h):
    pk1 = product_id(client, owner_h, "PK001")
    r = client.post(f"/api/products/{pk1}/adjust-stock", json={"new_stock": 10, "note": "Kiểm kê"},
                    headers=owner_h)
    assert r.status_code == 200
    assert r.json()["stock"] == 10


def test_product_update_cannot_change_stock_directly(client, owner_h):
    pk1 = product_id(client, owner_h, "PK001")
    client.put(f"/api/products/{pk1}", json={"stock": 999, "sale_price": 360_000}, headers=owner_h)
    p = client.get(f"/api/products/{pk1}", headers=owner_h).json()
    assert p["stock"] == 12
    assert p["sale_price"] == 360_000


# TC-STK-01 (SRS 11.3)
def test_low_stock_filter(client, owner_h):
    items = client.get("/api/products", params={"stock": "out"}, headers=owner_h).json()["items"]
    assert [p["code"] for p in items] == ["PK002"]


def test_import_quantity_and_cost_must_be_positive(client, owner_h):
    pk1 = product_id(client, owner_h, "PK001")
    for item in ({"product_id": pk1, "quantity": 1, "unit_cost": 0},
                 {"product_id": pk1, "quantity": 0, "unit_cost": 1000}):
        r = client.post("/api/imports", json={"items": [item]}, headers=owner_h)
        assert r.status_code == 422
        assert "Số lượng và giá nhập phải lớn hơn 0" in r.text
    r = client.post("/api/imports", json={"items": [
        {"new_product": {"name": "Sản phẩm mới", "sale_price": 0}, "quantity": 1, "unit_cost": 1000}]}, headers=owner_h)
    assert r.status_code == 422
    assert "Giá bán phải lớn hơn 0" in r.text
    assert stock_of(client, owner_h, "PK001") == 12
