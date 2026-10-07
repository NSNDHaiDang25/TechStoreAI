"""Test lập hóa đơn: tính tiền, giảm giá, kiểm tra tồn kho, phân quyền."""
from tests.helpers import product_id, stock_of


def make_invoice(client, h, items, **extra):
    return client.post("/api/invoices", json={"items": items, **extra}, headers=h)


def test_create_invoice_calculates_total_and_reduces_stock(client, staff_h):
    pk1, pk3 = product_id(client, staff_h, "PK001"), product_id(client, staff_h, "PK003")
    r = make_invoice(client, staff_h, [{"product_id": pk1, "quantity": 2}, {"product_id": pk3, "quantity": 1}],
                     discount=30_000, payment_method="transfer")  # "transfer": tên cũ, đã xác nhận tại quầy
    assert r.status_code == 201, r.text
    inv = r.json()
    assert inv["subtotal"] == 2 * 350_000 + 190_000
    assert inv["discount"] == 30_000
    assert inv["total"] == 860_000
    assert inv["payment_method"] == "bank_transfer" and inv["status"] == "paid"
    assert inv["code"].startswith("HD-") and inv["code"].endswith("-0001")  # BR-23: HD-yyyyMMdd-nnnn
    assert stock_of(client, staff_h, "PK001") == 10
    assert stock_of(client, staff_h, "PK003") == 49


def test_discount_percent(client, staff_h):
    pk1 = product_id(client, staff_h, "PK001")
    r = make_invoice(client, staff_h, [{"product_id": pk1, "quantity": 2}], discount_percent=10)
    assert r.json()["discount"] == 70_000
    assert r.json()["total"] == 630_000


def test_discount_greater_than_subtotal_rejected(client, staff_h):
    pk3 = product_id(client, staff_h, "PK003")
    r = make_invoice(client, staff_h, [{"product_id": pk3, "quantity": 1}], discount=500_000)
    assert r.status_code == 409
    assert stock_of(client, staff_h, "PK003") == 50  # rollback, không trừ kho


# TC-SAL-02 (SRS 11.3)
def test_insufficient_stock_rejected_and_nothing_changes(client, staff_h):
    pk1, pk3 = product_id(client, staff_h, "PK001"), product_id(client, staff_h, "PK003")
    r = make_invoice(client, staff_h, [{"product_id": pk3, "quantity": 1}, {"product_id": pk1, "quantity": 13}])
    assert r.status_code == 409
    assert "không đủ tồn kho" in r.json()["detail"]
    assert stock_of(client, staff_h, "PK003") == 50  # dòng hợp lệ trước đó cũng không bị trừ


def test_duplicate_lines_are_merged_for_stock_check(client, staff_h):
    pk1 = product_id(client, staff_h, "PK001")
    r = make_invoice(client, staff_h, [{"product_id": pk1, "quantity": 7}, {"product_id": pk1, "quantity": 6}])
    assert r.status_code == 409  # 7 + 6 = 13 > 12


def test_out_of_stock_product_cannot_be_sold(client, staff_h):
    pk2 = product_id(client, staff_h, "PK002")
    assert make_invoice(client, staff_h, [{"product_id": pk2, "quantity": 1}]).status_code == 409


def test_invalid_quantity_rejected(client, staff_h):
    pk1 = product_id(client, staff_h, "PK001")
    assert make_invoice(client, staff_h, [{"product_id": pk1, "quantity": 0}]).status_code == 422
    assert make_invoice(client, staff_h, []).status_code == 422


# TC-SAL-08 (SRS 11.3)
def test_staff_cancel_of_paid_invoice_needs_owner_approval(client, staff_h, owner_h):
    """FR-SAL-10: nhân viên gửi yêu cầu hủy hóa đơn đã thanh toán, chủ cửa hàng duyệt."""
    pk1 = product_id(client, staff_h, "PK001")
    inv = make_invoice(client, staff_h, [{"product_id": pk1, "quantity": 1}]).json()
    assert client.post(f"/api/invoices/{inv['id']}/cancel", json={"reason": "sai"}, headers=staff_h).status_code == 422
    r = client.post(f"/api/invoices/{inv['id']}/cancel", json={"reason": "Bấm nhầm sản phẩm"}, headers=staff_h)
    assert r.status_code == 200 and r.json()["status"] == "paid" and r.json()["cancel_requested_at"]
    assert stock_of(client, staff_h, "PK001") == 11
    assert client.get("/api/invoices", params={"cancel_requested": True}, headers=owner_h).json()["total"] == 1
    assert client.post(f"/api/invoices/{inv['id']}/cancel/approve", json={"approve": True},
                       headers=staff_h).status_code == 403
    r = client.post(f"/api/invoices/{inv['id']}/cancel/approve", json={"approve": True}, headers=owner_h)
    assert r.json()["status"] == "cancelled" and r.json()["cancel_reason"] == "Bấm nhầm sản phẩm"
    assert stock_of(client, staff_h, "PK001") == 12


def test_owner_can_reject_cancel_request(client, staff_h, owner_h):
    pk1 = product_id(client, staff_h, "PK001")
    inv = make_invoice(client, staff_h, [{"product_id": pk1, "quantity": 1}]).json()
    client.post(f"/api/invoices/{inv['id']}/cancel", json={"reason": "Bấm nhầm sản phẩm"}, headers=staff_h)
    r = client.post(f"/api/invoices/{inv['id']}/cancel/approve", json={"approve": False}, headers=owner_h)
    assert r.json()["status"] == "paid" and r.json()["cancel_requested_at"] is None


# FR-SAL-13
def test_staff_only_sees_own_invoices(client, staff_h, owner_h):
    pk1 = product_id(client, owner_h, "PK001")
    make_invoice(client, owner_h, [{"product_id": pk1, "quantity": 1}])
    make_invoice(client, staff_h, [{"product_id": pk1, "quantity": 1}])
    assert client.get("/api/invoices", headers=owner_h).json()["total"] == 2
    assert client.get("/api/invoices", headers=staff_h).json()["total"] == 1


# TC-AUT-02 (SRS 11.3)
def test_staff_cannot_see_cost_price(client, staff_h, owner_h):
    staff_view = client.get("/api/products", params={"q": "PK001"}, headers=staff_h).json()["items"][0]
    owner_view = client.get("/api/products", params={"q": "PK001"}, headers=owner_h).json()["items"][0]
    assert "cost_price" not in staff_view
    assert owner_view["cost_price"] == 220_000


def test_requires_login(client):
    assert client.get("/api/invoices").status_code == 401


# FR-SAL-13
def test_filter_invoices_by_status(client, owner_h):
    pk1 = product_id(client, owner_h, "PK001")
    a = make_invoice(client, owner_h, [{"product_id": pk1, "quantity": 1}]).json()
    make_invoice(client, owner_h, [{"product_id": pk1, "quantity": 1}])
    client.post(f"/api/invoices/{a['id']}/cancel", json={"reason": "Lập sai hóa đơn"}, headers=owner_h)
    assert client.get("/api/invoices", params={"status": "cancelled"}, headers=owner_h).json()["total"] == 1
    assert client.get("/api/invoices", params={"status": "paid"}, headers=owner_h).json()["total"] == 1


def test_staff_cannot_override_price(client, staff_h):
    pk1 = product_id(client, staff_h, "PK001")
    r = make_invoice(client, staff_h, [{"product_id": pk1, "quantity": 1, "unit_price": 1000}])
    assert r.json()["total"] == 350_000
