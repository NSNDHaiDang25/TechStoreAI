"""Test nhập hàng nhanh khi sắp hết: gợi ý số lượng, tránh đặt trùng phiếu nháp, mỗi nhà cung cấp một phiếu."""
from tests.helpers import product_id, stock_of


def supplier(client, owner_h, name="Công ty Phụ kiện An Phát"):
    r = client.post("/api/suppliers", json={"name": name}, headers=owner_h)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def suggestion(client, h, code):
    data = client.get("/api/purchase-orders/restock-suggestions", headers=h).json()
    return next((i for i in data["items"] if i["code"] == code), None), data


def test_suggestions_only_low_stock_and_hide_cost_from_staff(client, owner_h, staff_h):
    supplier(client, owner_h)
    item, data = suggestion(client, owner_h, "PK002")  # tồn 0, tối thiểu 5
    assert item["suggested_qty"] == 10 and item["unit_cost"] == 310_000 and data["suppliers"]
    assert suggestion(client, owner_h, "PK001")[0] is None  # tồn 12: không thiếu
    assert "unit_cost" not in suggestion(client, staff_h, "PK002")[0]


def test_owner_restocks_and_receives_immediately(client, owner_h):
    sup = supplier(client, owner_h)
    pid = product_id(client, owner_h, "PK002")
    r = client.post("/api/purchase-orders/quick-restock", headers=owner_h, json={
        "items": [{"product_id": pid, "quantity": 10, "supplier_id": sup, "unit_cost": 300_000}], "confirm": True})
    assert r.status_code == 201, r.text
    order = r.json()["orders"][0]
    assert order["status"] == "confirmed" and order["code"].startswith("PN-")
    assert stock_of(client, owner_h, "PK002") == 10
    assert suggestion(client, owner_h, "PK002")[0] is None  # đủ hàng, hết trong danh sách


def test_staff_drafts_are_counted_as_pending(client, owner_h, staff_h):
    sup_a, sup_b = supplier(client, owner_h), supplier(client, owner_h, "Đại lý Sạc Bình Minh")
    pk2 = product_id(client, staff_h, "PK002")
    # Thêm một sản phẩm sắp hết thứ hai để kiểm tra tách phiếu theo nhà cung cấp
    pk4 = client.post("/api/products", headers=owner_h, json={"code": "PK004", "name": "Cáp USB-C", "sale_price": 90_000,
                                                               "cost_price": 40_000, "stock": 1}).json()["id"]
    assert client.post("/api/purchase-orders/quick-restock", headers=staff_h, json={
        "items": [{"product_id": pk2, "quantity": 4, "supplier_id": sup_a}], "confirm": True}).status_code == 409
    r = client.post("/api/purchase-orders/quick-restock", headers=staff_h, json={
        "items": [{"product_id": pk2, "quantity": 4, "supplier_id": sup_a}, {"product_id": pk4, "quantity": 9, "supplier_id": sup_b}]})
    orders = r.json()["orders"]
    assert len(orders) == 2 and {o["status"] for o in orders} == {"draft"}
    item = suggestion(client, staff_h, "PK002")[0]
    assert item["pending_qty"] == 4 and item["suggested_qty"] == 6  # 10 - 0 tồn - 4 đang chờ
    assert stock_of(client, staff_h, "PK002") == 0  # nháp chưa cộng tồn
    dup = client.post("/api/purchase-orders/quick-restock", headers=staff_h, json={
        "items": [{"product_id": pk2, "quantity": 1, "supplier_id": sup_a}, {"product_id": pk2, "quantity": 2, "supplier_id": sup_b}]})
    assert dup.status_code == 409
