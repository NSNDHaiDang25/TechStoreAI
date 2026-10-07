"""Sản phẩm theo SRS 5.3, 5.4: mã vạch, VAT và bảo hành theo nhóm, tìm không dấu, audit đổi giá."""


# FR-CAT-01, FR-PRD-01
def test_product_inherits_vat_and_warranty_from_category(client, owner_h):
    cat = client.post("/api/categories", json={"name": "Laptop", "default_vat_rate": 8, "default_warranty_months": 24},
                      headers=owner_h).json()
    r = client.post("/api/products", json={"code": "lt-002", "name": "Laptop Dell", "sale_price": 20_000_000,
                                          "category_id": cat["id"], "barcode": "8934567890123"}, headers=owner_h)
    assert r.status_code == 201, r.text
    p = r.json()
    assert (p["code"], p["vat_rate"], p["warranty_months"], p["barcode"]) == ("LT-002", 8, 24, "8934567890123")
    dup = client.post("/api/products", json={"code": "LT-003", "name": "X", "sale_price": 1,
                                            "barcode": "8934567890123"}, headers=owner_h)
    assert dup.status_code == 400
    assert client.get("/api/products/by-code/8934567890123", headers=owner_h).json()["code"] == "LT-002"


# FR-PRD-02
def test_invalid_sku_and_barcode(client, owner_h):
    assert client.post("/api/products", json={"code": "mã có dấu", "name": "X", "sale_price": 1},
                       headers=owner_h).status_code == 422
    assert client.post("/api/products", json={"code": "OK-1", "name": "X", "sale_price": 1, "barcode": "12ab"},
                       headers=owner_h).status_code == 422
    assert client.post("/api/products", json={"code": "OK-2", "name": "X", "sale_price": 1, "vat_rate": 101},
                       headers=owner_h).status_code == 422


# FR-PRD-06, FR-SAL-02
def test_search_ignores_vietnamese_accents(client, staff_h):
    items = client.get("/api/products", params={"q": "sac nhanh"}, headers=staff_h).json()["items"]
    assert [p["code"] for p in items] == ["PK003"]
    assert client.get("/api/products", params={"q": "TAI NGHE"}, headers=staff_h).json()["total"] == 2


# FR-PRD-06, FR-PRD-07
def test_price_range_and_stock_state(client, staff_h):
    items = client.get("/api/products", params={"min_price": 300_000, "max_price": 400_000}, headers=staff_h).json()["items"]
    assert [p["code"] for p in items] == ["PK001"]
    states = {p["code"]: p["stock_state"] for p in client.get("/api/products", headers=staff_h).json()["items"]}
    assert states == {"PK001": "in", "PK002": "out", "PK003": "in"}


def test_price_change_is_audited(client, owner_h):
    pid = client.get("/api/products", params={"q": "PK001"}, headers=owner_h).json()["items"][0]["id"]
    client.put(f"/api/products/{pid}", json={"sale_price": 390_000}, headers=owner_h)
    client.put(f"/api/products/{pid}", json={"name": "Đổi tên thôi"}, headers=owner_h)
    logs = client.get("/api/audit-logs", params={"action": "PRICE_CHANGE"}, headers=owner_h).json()["items"]
    assert len(logs) == 1 and "350000" in logs[0]["old_value"] and "390000" in logs[0]["new_value"]


# FR-PRD-03
def test_discontinued_status(client, owner_h):
    pid = client.get("/api/products", params={"q": "PK003"}, headers=owner_h).json()["items"][0]["id"]
    r = client.put(f"/api/products/{pid}", json={"status": "discontinued"}, headers=owner_h)
    assert r.status_code == 200 and r.json()["status"] == "discontinued"
    assert client.get("/api/products", params={"status": "discontinued"}, headers=owner_h).json()["total"] == 1


# FR-CAT-01
def test_category_with_products_cannot_be_deleted_but_can_be_hidden(client, owner_h):
    cat = client.get("/api/categories", headers=owner_h).json()[0]
    assert client.delete(f"/api/categories/{cat['id']}", headers=owner_h).status_code == 400
    r = client.put(f"/api/categories/{cat['id']}", json={"name": cat["name"], "is_active": False}, headers=owner_h)
    assert r.json()["is_active"] is False
    assert client.get("/api/categories", params={"active_only": True}, headers=owner_h).json() == []


def test_staff_can_view_stock_card(client, staff_h, owner_h):
    pid = client.get("/api/products", params={"q": "PK001"}, headers=owner_h).json()["items"][0]["id"]
    client.post(f"/api/products/{pid}/adjust-stock", json={"new_stock": 10, "note": "Kiểm kê"}, headers=owner_h)
    moves = client.get("/api/stock-movements", params={"product_id": pid}, headers=staff_h).json()["items"]
    assert moves[0]["stock_before"] == 12 and moves[0]["stock_after"] == 10
