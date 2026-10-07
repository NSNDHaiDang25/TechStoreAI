"""Nhà cung cấp và phiếu nhập: nháp -> xác nhận -> hủy, giá vốn bình quân, serial, phân quyền."""
from tests.helpers import product_id, stock_of


def make_supplier(client, h, **kw):
    body = {"name": "Công ty Phân phối Số", "phone": "0281234567", "email": "ban@nppso.vn", **kw}
    r = client.post("/api/suppliers", json=body, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def make_serial_product(client, h, code="LT001"):
    r = client.post("/api/products", json={"code": code, "name": "Laptop Asus Vivobook 15", "sale_price": 15_990_000,
                                          "track_serial": True}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def po(client, h, supplier_id, items, **kw):
    return client.post("/api/purchase-orders", json={"supplier_id": supplier_id, "items": items, **kw}, headers=h)


# ---------------------------------------------------------------- Nhà cung cấp
# FR-SUP-01
def test_supplier_crud_and_unique_code(client, owner_h, staff_h):
    s = make_supplier(client, owner_h)
    assert s["code"] == "NCC01" and s["status"] == "active"
    assert make_supplier(client, owner_h, name="NCC 2")["code"] == "NCC02"
    dup = client.post("/api/suppliers", json={"code": "NCC01", "name": "Trùng"}, headers=owner_h)
    assert dup.status_code == 400
    assert client.post("/api/suppliers", json={"name": "X"}, headers=staff_h).status_code == 403
    staff_view = client.get("/api/suppliers", headers=staff_h).json()
    assert len(staff_view) == 2 and "total_amount" not in staff_view[0]
    r = client.put(f"/api/suppliers/{s['id']}", json={"name": "Đổi tên", "phone": "0909 123.456"}, headers=owner_h)
    assert r.json()["name"] == "Đổi tên" and r.json()["phone"] == "0909123456"


def test_supplier_with_orders_is_deactivated_not_deleted(client, owner_h):
    s = make_supplier(client, owner_h)
    pk1 = product_id(client, owner_h, "PK001")
    po(client, owner_h, s["id"], [{"product_id": pk1, "quantity": 1, "unit_cost": 200_000}])
    r = client.delete(f"/api/suppliers/{s['id']}", headers=owner_h)
    assert r.status_code == 200 and "ngừng hợp tác" in r.json()["message"]
    assert client.get(f"/api/suppliers/{s['id']}", headers=owner_h).json()["status"] == "inactive"
    # BR-21: không lập phiếu với nhà cung cấp ngừng hợp tác
    r = po(client, owner_h, s["id"], [{"product_id": pk1, "quantity": 1, "unit_cost": 200_000}])
    assert r.status_code == 409
    empty = make_supplier(client, owner_h, name="Chưa giao dịch")
    assert client.delete(f"/api/suppliers/{empty['id']}", headers=owner_h).json()["message"] == "Đã xóa nhà cung cấp"


# ---------------------------------------------------------------- Phiếu nhập
# TC-PUR-01, TC-PUR-04, FR-PUR-01 (SRS 11.3)
def test_draft_does_not_change_stock_until_confirmed(client, owner_h):
    s = make_supplier(client, owner_h)
    pk1 = product_id(client, owner_h, "PK001")
    r = po(client, owner_h, s["id"], [{"product_id": pk1, "quantity": 8, "unit_cost": 230_000}])
    assert r.status_code == 201, r.text
    draft = r.json()
    assert draft["status"] == "draft" and draft["code"].startswith("PN-") and len(draft["code"]) == 15
    assert stock_of(client, owner_h, "PK001") == 12
    r = client.post(f"/api/purchase-orders/{draft['id']}/confirm", headers=owner_h)
    assert r.status_code == 200 and r.json()["status"] == "confirmed" and r.json()["received_at"]
    assert stock_of(client, owner_h, "PK001") == 20
    assert client.get(f"/api/products/{pk1}", headers=owner_h).json()["cost_price"] == 224_000  # BR-19
    again = client.post(f"/api/purchase-orders/{draft['id']}/confirm", headers=owner_h)
    assert again.status_code == 409


# FR-PUR-07
def test_codes_increase_within_day(client, owner_h):
    s = make_supplier(client, owner_h)
    pk1 = product_id(client, owner_h, "PK001")
    a = po(client, owner_h, s["id"], [{"product_id": pk1, "quantity": 1}]).json()["code"]
    b = po(client, owner_h, s["id"], [{"product_id": pk1, "quantity": 1}]).json()["code"]
    assert a.endswith("-001") and b.endswith("-002")


# FR-PUR-08
def test_staff_creates_draft_without_seeing_cost(client, owner_h, staff_h):
    s = make_supplier(client, owner_h)
    pk1 = product_id(client, staff_h, "PK001")
    r = po(client, staff_h, s["id"], [{"product_id": pk1, "quantity": 5, "unit_cost": 1}])
    assert r.status_code == 201
    draft = r.json()
    assert draft["total"] is None and draft["items"][0]["unit_cost"] is None
    assert po(client, staff_h, s["id"], [{"product_id": pk1, "quantity": 5}], confirm=True).status_code == 409
    assert client.post(f"/api/purchase-orders/{draft['id']}/confirm", headers=staff_h).status_code == 403
    # Nhân viên không gửi được giá nhập: dòng chưa có giá thì chủ phải điền trước khi xác nhận
    assert client.post(f"/api/purchase-orders/{draft['id']}/confirm", headers=owner_h).status_code == 409
    upd = client.put(f"/api/purchase-orders/{draft['id']}", json={"supplier_id": s["id"], "items": [
        {"product_id": pk1, "quantity": 5, "unit_cost": 210_000}], "confirm": True}, headers=owner_h)
    assert upd.status_code == 200, upd.text
    assert upd.json()["status"] == "confirmed" and upd.json()["total"] == 1_050_000
    assert stock_of(client, owner_h, "PK001") == 17


def test_edit_and_delete_only_drafts(client, owner_h):
    s = make_supplier(client, owner_h)
    pk1, pk3 = product_id(client, owner_h, "PK001"), product_id(client, owner_h, "PK003")
    d = po(client, owner_h, s["id"], [{"product_id": pk1, "quantity": 2, "unit_cost": 200_000}]).json()
    r = client.put(f"/api/purchase-orders/{d['id']}", json={"supplier_id": s["id"], "note": "sửa", "items": [
        {"product_id": pk3, "quantity": 4, "unit_cost": 90_000}]}, headers=owner_h)
    assert [i["product_code"] for i in r.json()["items"]] == ["PK003"] and r.json()["total"] == 360_000
    assert client.delete(f"/api/purchase-orders/{d['id']}", headers=owner_h).status_code == 200
    c = po(client, owner_h, s["id"], [{"product_id": pk1, "quantity": 1, "unit_cost": 200_000}], confirm=True).json()
    assert client.delete(f"/api/purchase-orders/{c['id']}", headers=owner_h).status_code == 400
    put = client.put(f"/api/purchase-orders/{c['id']}", json={"supplier_id": s["id"], "items": [
        {"product_id": pk1, "quantity": 9, "unit_cost": 1}]}, headers=owner_h)
    assert put.status_code == 409


def test_cancel_confirmed_order_restores_stock_and_cost(client, owner_h):
    s = make_supplier(client, owner_h)
    pk1 = product_id(client, owner_h, "PK001")
    c = po(client, owner_h, s["id"], [{"product_id": pk1, "quantity": 8, "unit_cost": 230_000}], confirm=True).json()
    assert client.post(f"/api/purchase-orders/{c['id']}/cancel", json={"reason": "x"}, headers=owner_h).status_code == 422
    r = client.post(f"/api/purchase-orders/{c['id']}/cancel", json={"reason": "Nhập nhầm hàng"}, headers=owner_h)
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    p = client.get(f"/api/products/{pk1}", headers=owner_h).json()
    assert (p["stock"], p["cost_price"]) == (12, 220_000)
    moves = client.get("/api/stock-movements", params={"type": "import_cancel"}, headers=owner_h).json()["items"]
    assert moves[0]["change"] == -8 and moves[0]["stock_before"] == 20


# TC-PUR-05 (SRS 11.3)
def test_cannot_cancel_when_stock_already_sold(client, owner_h):
    s = make_supplier(client, owner_h)
    pk3 = product_id(client, owner_h, "PK003")
    c = po(client, owner_h, s["id"], [{"product_id": pk3, "quantity": 5, "unit_cost": 90_000}], confirm=True).json()
    client.post("/api/products/%d/adjust-stock" % pk3, json={"new_stock": 3, "note": "Kiểm kê thiếu"}, headers=owner_h)
    r = client.post(f"/api/purchase-orders/{c['id']}/cancel", json={"reason": "Nhập nhầm hàng"}, headers=owner_h)
    assert r.status_code == 409 and "chỉ còn 3" in r.json()["detail"]  # BR-22


# FR-PRD-09
def test_serial_product_requires_matching_serials(client, owner_h):
    s = make_supplier(client, owner_h)
    lt = make_serial_product(client, owner_h)
    short = po(client, owner_h, s["id"], [{"product_id": lt["id"], "quantity": 2, "unit_cost": 14_000_000,
                                           "serials": ["SNVIVO0001"]}], confirm=True)
    assert short.status_code == 409 and "đủ 2 serial" in short.json()["detail"]
    dup = po(client, owner_h, s["id"], [{"product_id": lt["id"], "quantity": 2, "unit_cost": 14_000_000,
                                         "serials": ["SNVIVO0001", "snvivo0001"]}])
    assert dup.status_code == 409
    bad_imei = po(client, owner_h, s["id"], [{"product_id": lt["id"], "quantity": 1, "unit_cost": 14_000_000,
                                              "serials": ["490154203237519"]}])
    assert bad_imei.status_code == 409 and "Luhn" in bad_imei.json()["detail"]
    ok = po(client, owner_h, s["id"], [{"product_id": lt["id"], "quantity": 2, "unit_cost": 14_000_000,
                                        "serials": ["SNVIVO0001", "490154203237518"]}], confirm=True)
    assert ok.status_code == 201, ok.text
    serials = client.get(f"/api/products/{lt['id']}/serials", headers=owner_h).json()
    assert {x["serial_no"] for x in serials} == {"SNVIVO0001", "490154203237518"}
    assert all(x["status"] == "in_stock" for x in serials)
    assert stock_of(client, owner_h, "LT001") == 2
    again = po(client, owner_h, s["id"], [{"product_id": lt["id"], "quantity": 1, "unit_cost": 14_000_000,
                                           "serials": ["SNVIVO0001"]}], confirm=True)
    assert again.status_code == 409 and "đã có trong hệ thống" in again.json()["detail"]
    pk1 = product_id(client, owner_h, "PK001")
    wrong = po(client, owner_h, s["id"], [{"product_id": pk1, "quantity": 1, "unit_cost": 1, "serials": ["ABCDE1"]}])
    assert wrong.status_code == 409  # sản phẩm không theo serial


# FR-PRD-10
def test_serial_product_stock_follows_serials(client, owner_h):
    s = make_supplier(client, owner_h)
    lt = make_serial_product(client, owner_h)
    po(client, owner_h, s["id"], [{"product_id": lt["id"], "quantity": 2, "unit_cost": 14_000_000,
                                   "serials": ["SNA00001", "SNA00002"]}], confirm=True)
    adj = client.post(f"/api/products/{lt['id']}/adjust-stock", json={"new_stock": 5, "note": "kiểm kê"},
                      headers=owner_h)
    assert adj.status_code == 409
    serial = client.get(f"/api/products/{lt['id']}/serials", headers=owner_h).json()[0]
    r = client.put(f"/api/serials/{serial['id']}", json={"status": "defective", "note": "Máy lỗi màn hình"},
                   headers=owner_h)
    assert r.status_code == 200 and r.json()["status"] == "defective"
    assert stock_of(client, owner_h, "LT001") == 1
    found = client.get("/api/products/by-code/SNA00002", headers=owner_h).json()
    assert found["code"] == "LT001" and found["serial"]["status"] == "in_stock"


# TC-PUR-05 (SRS 11.3)
def test_cancel_order_with_sold_serial_is_blocked(client, owner_h, db):
    from app.models import ProductSerial
    s = make_supplier(client, owner_h)
    lt = make_serial_product(client, owner_h)
    c = po(client, owner_h, s["id"], [{"product_id": lt["id"], "quantity": 1, "unit_cost": 14_000_000,
                                       "serials": ["SNSOLD001"]}], confirm=True).json()
    serial = db.query(ProductSerial).filter_by(serial_no="SNSOLD001").one()
    serial.status = "sold"
    db.commit()
    r = client.post(f"/api/purchase-orders/{c['id']}/cancel", json={"reason": "Nhập nhầm hàng"}, headers=owner_h)
    assert r.status_code == 409 and "đã bán" in r.json()["detail"]


def test_supplier_history(client, owner_h):
    s = make_supplier(client, owner_h)
    pk1 = product_id(client, owner_h, "PK001")
    po(client, owner_h, s["id"], [{"product_id": pk1, "quantity": 2, "unit_cost": 200_000}], confirm=True)
    po(client, owner_h, s["id"], [{"product_id": pk1, "quantity": 1, "unit_cost": 200_000}])
    detail = client.get(f"/api/suppliers/{s['id']}", headers=owner_h).json()
    assert len(detail["purchase_orders"]) == 2
    listed = next(x for x in client.get("/api/suppliers", headers=owner_h).json() if x["id"] == s["id"])
    assert listed["order_count"] == 1 and listed["total_amount"] == 400_000


def test_audit_log_on_confirm(client, owner_h):
    s = make_supplier(client, owner_h)
    pk1 = product_id(client, owner_h, "PK001")
    po(client, owner_h, s["id"], [{"product_id": pk1, "quantity": 2, "unit_cost": 200_000}], confirm=True)
    actions = [i["action"] for i in client.get("/api/audit-logs", headers=owner_h).json()["items"]]
    assert "PURCHASE_CONFIRM" in actions
