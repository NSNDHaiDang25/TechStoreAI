"""Bán hàng theo SRS: hóa đơn mẫu mục 3.4 (TC-SAL-01), khuyến mãi, điểm, hạng, chờ chuyển khoản, nháp,
serial, bảo hành, hủy, in hóa đơn."""
from datetime import timedelta

import pytest

from app.models import Customer, Invoice, Promotion, Warranty, now
from app.services import loyalty
from tests.helpers import product_id, stock_of

DAY = timedelta(days=1)


def iso(dt):
    return dt.replace(microsecond=0).isoformat()


def add_product(client, h, code, name, price, cost=0, **kw):
    r = client.post("/api/products", json={"code": code, "name": name, "sale_price": price, "cost_price": cost,
                                          "stock": kw.pop("stock", 0 if kw.get("track_serial") else 20), **kw},
                    headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def add_customer(client, h, name="Trần Văn Nam", phone="0912345678", **kw):
    r = client.post("/api/customers", json={"name": name, "phone": phone, **kw}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def add_promo(client, h, **kw):
    body = {"name": "Khuyến mãi", "promo_type": "fixed_amount", "scope": "invoice", "discount_value": 500_000,
            "start_at": iso(now() - DAY), "end_at": iso(now() + 30 * DAY), **kw}
    r = client.post("/api/promotions", json=body, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def set_customer(db, cid, *, points=None, spent=None):
    c = db.get(Customer, cid)
    db.refresh(c)
    if points is not None:
        c.loyalty_points = points
    if spent is not None:
        c.total_spent = spent
        loyalty.recompute_tier(db, c)
    db.commit()


def sell(client, h, items, **kw):
    return client.post("/api/invoices", json={"items": items, **kw}, headers=h)


@pytest.fixture
def sample(client, owner_h, db):
    """Bộ số chung của SRS mục 3.4."""
    p = {
        "laptop": add_product(client, owner_h, "LT-VIVO15", "Laptop Asus Vivobook 15", 15_990_000, 14_000_000),
        "mouse": add_product(client, owner_h, "CH-M331", "Chuột Logitech M331", 290_000, 150_000),
        "headset": add_product(client, owner_h, "TN-CH520", "Tai nghe Sony WH-CH520", 1_190_000, 800_000),
        "charger": add_product(client, owner_h, "SAC-ANKER20", "Sạc Anker 20W", 350_000, 180_000),
    }
    nam = add_customer(client, owner_h)
    set_customer(db, nam["id"], points=420, spent=25_000_000)  # hạng Bạc, hệ số 1,2
    add_promo(client, owner_h, name="Giảm 500k", code="TECH10")
    items = [{"product_id": p["laptop"]["id"], "quantity": 1}, {"product_id": p["mouse"]["id"], "quantity": 2},
             {"product_id": p["headset"]["id"], "quantity": 1}, {"product_id": p["charger"]["id"], "quantity": 1}]
    return {"products": p, "customer": nam, "items": items}


# ---------------------------------------------------------------- TC-SAL-01
# TC-SAL-01 (SRS 11.3)
def test_preview_matches_srs_example(client, staff_h, sample):
    r = client.post("/api/invoices/preview", json={"items": sample["items"], "customer_id": sample["customer"]["id"],
                                                    "promo_code": "tech10", "points_used": 200}, headers=staff_h)
    assert r.status_code == 200, r.text
    cart = r.json()
    assert (cart["subtotal"], cart["discount"], cart["total"], cart["vat_amount"], cart["points_earned"]) == \
        (18_110_000, 520_000, 17_590_000, 1_599_091, 2_110)
    assert [ln["allocated"] for ln in cart["lines"]] == [459_128, 16_654, 34_169, 10_049]
    assert [ln["net_total"] for ln in cart["lines"]] == [15_530_872, 563_346, 1_155_831, 339_951]
    assert cart["revenue_net"] == 15_990_909
    assert cart["promotions"][0]["code"] == "TECH10"


# TC-SAL-01 (SRS 11.3)
def test_checkout_srs_example_updates_points_tier_and_warranty(client, staff_h, sample, db):
    nam = sample["customer"]
    r = sell(client, staff_h, sample["items"], customer_id=nam["id"], promo_code="TECH10", points_used=200,
             payment_method="cash", cash_received=18_000_000)
    assert r.status_code == 201, r.text
    inv = r.json()
    assert (inv["status"], inv["total"], inv["vat_amount"], inv["points_earned"], inv["change"]) == \
        ("paid", 17_590_000, 1_599_091, 2_110, 410_000)
    assert [it["discount_amount"] for it in inv["items"]] == [459_128, 16_654, 34_169, 10_049]
    c = client.get(f"/api/customers/{nam['id']}", headers=staff_h).json()
    assert c["loyalty_points"] == 420 - 200 + 2_110 == 2_330
    assert c["total_spent"] == 25_000_000 + 17_590_000 and c["tier_name"] == "Bạc"  # chưa tới 50 triệu
    assert [h["txn_type"] for h in c["points_history"][:2]] == ["earn", "redeem"]
    assert len(c["warranties"]) == 4
    w = db.query(Warranty).first()
    assert (w.end_date - w.start_date).days in range(365, 367)  # 12 tháng
    promo = db.query(Promotion).filter_by(code="TECH10").one()
    db.refresh(promo)
    assert promo.used_count == 1


# ---------------------------------------------------------------- Khuyến mãi
# TC-PRM-01 (SRS 11.3)
def test_voucher_rejections_explain_reason(client, owner_h, staff_h, sample):
    items = sample["items"][:1]
    add_promo(client, owner_h, name="Hết hạn", code="OLD", start_at=iso(now() - 10 * DAY), end_at=iso(now() - DAY))
    add_promo(client, owner_h, name="Tối thiểu", code="BIG", min_invoice_amount=50_000_000)
    add_promo(client, owner_h, name="Một lượt", code="ONCE", usage_limit=1)
    paused = add_promo(client, owner_h, name="Tạm dừng", code="PAUSE")
    client.put(f"/api/promotions/{paused['id']}/status", json={"status": "paused"}, headers=owner_h)

    def reason(code):
        r = client.post("/api/promotions/validate-code", json={"code": code, "items": items}, headers=staff_h).json()
        assert r["valid"] is False
        return r["reason"]

    assert "không tồn tại" in reason("NOPE")
    assert "hết hạn" in reason("OLD")
    assert "tối thiểu" in reason("BIG")
    assert "tạm dừng" in reason("PAUSE")
    assert sell(client, staff_h, items, promo_code="ONCE").status_code == 201
    assert "hết lượt" in reason("ONCE")
    ok = client.post("/api/promotions/validate-code", json={"code": "TECH10", "items": items}, headers=staff_h).json()
    assert ok["valid"] and ok["cart"]["discount"] == 500_000


# TC-PRM-02, FR-PRM-01, FR-PRM-02, FR-PRM-04, FR-PRM-05 (SRS 11.3)
def test_best_line_promotion_per_product_and_auto_invoice_promo(client, owner_h, staff_h, sample):
    p = sample["products"]
    add_promo(client, owner_h, name="Chuột -10%", promo_type="percent", scope="product",
              target_id=p["mouse"]["id"], discount_value=10)
    add_promo(client, owner_h, name="Chuột -50k", scope="product", target_id=p["mouse"]["id"], discount_value=50_000)
    add_promo(client, owner_h, name="Đơn từ 1 triệu -5% tối đa 100k", promo_type="percent", discount_value=5,
              max_discount=100_000, min_invoice_amount=1_000_000)
    cart = client.post("/api/invoices/preview", json={"items": [
        {"product_id": p["mouse"]["id"], "quantity": 2}, {"product_id": p["headset"]["id"], "quantity": 1}]},
        headers=staff_h).json()
    mouse = cart["lines"][0]
    assert mouse["line_promo"] == 100_000 and mouse["promo_name"] == "Chuột -50k"  # BR-06: 2 x 50k > 10% x 580k
    # Tự động cấp hóa đơn: 5% x (580k + 1.190k - 100k) = 83.500, dưới mức tối đa 100k
    assert next(x for x in cart["promotions"] if x["scope"] == "invoice")["amount"] == 83_500
    assert cart["total"] == 580_000 + 1_190_000 - 100_000 - 83_500
    # Có voucher cấp hóa đơn thì không áp thêm khuyến mãi tự động cấp hóa đơn (BR-05)
    cart = client.post("/api/invoices/preview", json={"items": [
        {"product_id": p["mouse"]["id"], "quantity": 2}, {"product_id": p["headset"]["id"], "quantity": 1}],
        "promo_code": "TECH10"}, headers=staff_h).json()
    assert [x["name"] for x in cart["promotions"] if x["scope"] == "invoice"] == ["Giảm 500k"]


def test_staff_cannot_manage_promotions(client, staff_h):
    assert client.post("/api/promotions", json={}, headers=staff_h).status_code in (403, 422)
    assert client.get("/api/promotions", headers=staff_h).status_code == 200


# ---------------------------------------------------------------- Điểm
# TC-LOY-02 (SRS 11.3)
def test_points_limits(client, staff_h, sample, db):
    nam = sample["customer"]
    set_customer(db, nam["id"], points=100_000)
    items = sample["items"][1:2]  # 2 chuột = 580.000
    r = client.post("/api/invoices/preview", json={"items": items, "customer_id": nam["id"]}, headers=staff_h).json()
    assert r["points_max"] == 2_900  # 50% x 580.000 / 100
    # TC-LOY-02: dùng vượt 50% giá trị hóa đơn thì tự hạ về mức tối đa và thông báo (UC-22 luồng 2a)
    over = client.post("/api/invoices/preview", json={"items": items, "customer_id": nam["id"], "points_used": 2_901},
                       headers=staff_h).json()
    assert over["points_used"] == 2_900 and over["points_discount"] == 290_000
    assert any("2901 xuống 2900" in w for w in over["warnings"])
    walk_in = sell(client, staff_h, items, points_used=1)
    assert walk_in.status_code == 409 and "Khách lẻ" in walk_in.json()["detail"]
    ok = sell(client, staff_h, items, customer_id=nam["id"], points_used=1_000).json()
    assert ok["total"] == 480_000 and ok["points_discount"] == 100_000


# FR-SAL-06
def test_walk_in_customer_earns_no_points(client, staff_h, sample):
    inv = sell(client, staff_h, sample["items"][:1]).json()
    assert inv["points_earned"] == 0 and inv["customer_name"] == "Khách lẻ"


def test_owner_adjusts_points_with_reason(client, owner_h, staff_h, sample):
    cid = sample["customer"]["id"]
    assert client.post(f"/api/customers/{cid}/points", json={"points": 50, "reason": "Tặng sinh nhật"},
                       headers=staff_h).status_code == 403
    assert client.post(f"/api/customers/{cid}/points", json={"points": 50, "reason": ""},
                       headers=owner_h).status_code == 422
    r = client.post(f"/api/customers/{cid}/points", json={"points": 50, "reason": "Tặng sinh nhật"}, headers=owner_h)
    assert r.json()["balance"] == 470
    assert client.post(f"/api/customers/{cid}/points", json={"points": -1000, "reason": "Trừ nhầm điểm"},
                       headers=owner_h).status_code == 400
    assert client.get("/api/audit-logs", params={"action": "POINTS_ADJUST"}, headers=owner_h).json()["total"] == 1


# ---------------------------------------------------------------- Chuyển khoản chờ xác nhận
# TC-PAY-02 (SRS 11.3)
def test_bank_transfer_waits_for_confirmation(client, staff_h, sample):
    nam = sample["customer"]
    items = sample["items"][2:3]
    r = sell(client, staff_h, items, customer_id=nam["id"], payment_method="bank_transfer")
    inv = r.json()
    assert inv["status"] == "pending_payment" and inv["paid_at"] is None
    assert inv["pending_deadline"] and stock_of(client, staff_h, "TN-CH520") == 19
    qr = client.get(f"/api/invoices/{inv['id']}/qr", headers=staff_h).json()
    assert qr["amount"] == 1_190_000 and qr["svg"].startswith("<svg") and "54071190000" in qr["payload"]
    before = client.get(f"/api/customers/{nam['id']}", headers=staff_h).json()["loyalty_points"]
    r = client.post(f"/api/invoices/{inv['id']}/confirm-payment", json={}, headers=staff_h)
    assert r.status_code == 200 and r.json()["status"] == "paid" and r.json()["paid_at"]
    assert r.json()["payments"][-1]["status"] == "confirmed"
    after = client.get(f"/api/customers/{nam['id']}", headers=staff_h).json()["loyalty_points"]
    assert after - before == 142  # 119 x 1,2
    assert client.post(f"/api/invoices/{inv['id']}/confirm-payment", headers=staff_h).status_code == 409


def test_change_payment_method_while_pending(client, staff_h, sample):
    inv = sell(client, staff_h, sample["items"][2:3], payment_method="bank_transfer").json()
    bad = client.post(f"/api/invoices/{inv['id']}/confirm-payment", json={"payment_method": "card"}, headers=staff_h)
    assert bad.status_code == 422
    r = client.post(f"/api/invoices/{inv['id']}/confirm-payment",
                    json={"payment_method": "card", "payment_ref": "POS998877"}, headers=staff_h)
    assert r.json()["payment_method"] == "card" and r.json()["status"] == "paid"


# TC-SAL-10 (SRS 11.3)
def test_pending_invoice_expires_after_30_minutes(client, staff_h, owner_h, sample, db):
    inv = sell(client, staff_h, sample["items"][:1], payment_method="bank_transfer", promo_code="TECH10").json()
    assert stock_of(client, staff_h, "LT-VIVO15") == 19
    row = db.get(Invoice, inv["id"])
    row.created_at = now() - timedelta(minutes=31)
    db.commit()
    r = client.get(f"/api/invoices/{inv['id']}", headers=staff_h).json()
    assert r["status"] == "cancelled" and "30 phút" in r["cancel_reason"]
    assert stock_of(client, staff_h, "LT-VIVO15") == 20
    promo = db.query(Promotion).filter_by(code="TECH10").one()
    db.refresh(promo)
    assert promo.used_count == 0  # BR-09


def test_card_requires_pos_reference(client, staff_h, sample):
    r = sell(client, staff_h, sample["items"][:1], payment_method="card")
    assert r.status_code == 422 and "POS" in r.json()["detail"]


# ---------------------------------------------------------------- Nháp
def test_draft_keeps_cart_without_touching_stock(client, staff_h, sample):
    items = sample["items"][1:2]
    d = client.post("/api/invoices/drafts", json={"items": items, "customer_id": sample["customer"]["id"]},
                    headers=staff_h)
    assert d.status_code == 201, d.text
    draft = d.json()
    assert draft["status"] == "draft" and stock_of(client, staff_h, "CH-M331") == 20
    upd = client.post("/api/invoices/drafts", json={"items": [{**items[0], "quantity": 3}], "draft_id": draft["id"]},
                      headers=staff_h).json()
    assert upd["id"] == draft["id"] and upd["items"][0]["quantity"] == 3
    assert client.get("/api/invoices", params={"status": "draft"}, headers=staff_h).json()["total"] == 1
    paid = sell(client, staff_h, [{**items[0], "quantity": 3}], draft_id=draft["id"]).json()
    assert paid["id"] == draft["id"] and paid["code"] == draft["code"] and paid["status"] == "paid"
    assert stock_of(client, staff_h, "CH-M331") == 17


# ---------------------------------------------------------------- Serial
@pytest.fixture
def phone_with_serials(client, owner_h):
    p = add_product(client, owner_h, "DT-IP15", "iPhone 15 128GB", 19_990_000, 17_000_000, track_serial=True)
    sup = client.post("/api/suppliers", json={"name": "NPP Apple"}, headers=owner_h).json()
    r = client.post("/api/purchase-orders", json={"supplier_id": sup["id"], "confirm": True, "items": [
        {"product_id": p["id"], "quantity": 2, "unit_cost": 17_000_000, "serials": ["IMEI0000001", "IMEI0000002"]}]},
        headers=owner_h)
    assert r.status_code == 201, r.text
    return p


# TC-SAL-03, FR-PRD-09 (SRS 11.3)
def test_serial_must_be_chosen_and_is_marked_sold(client, staff_h, owner_h, phone_with_serials):
    pid = phone_with_serials["id"]
    no_serial = sell(client, staff_h, [{"product_id": pid, "quantity": 1}])
    assert no_serial.status_code == 422 and "serial" in no_serial.json()["detail"]
    two = sell(client, staff_h, [{"product_id": pid, "quantity": 2, "serial_no": "IMEI0000001"}])
    assert two.status_code == 409
    inv = sell(client, staff_h, [{"product_id": pid, "quantity": 1, "serial_no": "imei0000001"}]).json()
    assert inv["items"][0]["serial_no"] == "IMEI0000001"
    serials = {s["serial_no"]: s["status"] for s in client.get(f"/api/products/{pid}/serials", headers=staff_h).json()}
    assert serials == {"IMEI0000001": "sold", "IMEI0000002": "in_stock"}
    again = sell(client, staff_h, [{"product_id": pid, "quantity": 1, "serial_no": "IMEI0000001"}])
    assert again.status_code == 409 and "không còn trong kho" in again.json()["detail"]
    r = client.post(f"/api/invoices/{inv['id']}/cancel", json={"reason": "Lập sai hóa đơn"}, headers=owner_h)
    assert r.json()["status"] == "cancelled"
    serials = {s["serial_no"]: s["status"] for s in client.get(f"/api/products/{pid}/serials", headers=staff_h).json()}
    assert serials["IMEI0000001"] == "in_stock" and stock_of(client, staff_h, "DT-IP15") == 2


# ---------------------------------------------------------------- Giá vốn, hủy
# TC-SAL-11 (SRS 11.3)
def test_staff_cannot_sell_below_cost_but_owner_can(client, staff_h, owner_h, sample):
    add_promo(client, owner_h, name="Xả kho tai nghe", promo_type="percent", scope="product",
              target_id=sample["products"]["headset"]["id"], discount_value=50)
    items = sample["items"][2:3]
    r = sell(client, staff_h, items)
    assert r.status_code == 409 and "giá vốn" in r.json()["detail"]
    r = sell(client, owner_h, items)
    assert r.status_code == 201 and r.json()["warnings"]
    assert client.get("/api/audit-logs", params={"action": "INVOICE_BELOW_COST"}, headers=owner_h).json()["total"] == 1


# TC-SAL-07 (SRS 11.3)
def test_cancel_paid_invoice_reverses_points_tier_and_voucher(client, owner_h, sample, db):
    nam = sample["customer"]
    inv = sell(client, owner_h, sample["items"], customer_id=nam["id"], promo_code="TECH10", points_used=200).json()
    r = client.post(f"/api/invoices/{inv['id']}/cancel", json={"reason": "Lập sai khách hàng"}, headers=owner_h)
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    c = client.get(f"/api/customers/{nam['id']}", headers=owner_h).json()
    assert (c["loyalty_points"], c["total_spent"], c["tier_name"]) == (420, 25_000_000, "Bạc")
    assert c["warranties"] == []
    promo = db.query(Promotion).filter_by(code="TECH10").one()
    db.refresh(promo)
    assert promo.used_count == 0
    assert stock_of(client, owner_h, "LT-VIVO15") == 20


# TC-SAL-09 (SRS 11.3)
def test_paid_invoice_can_only_be_cancelled_on_its_day(client, owner_h, sample, db):
    inv = sell(client, owner_h, sample["items"][:1]).json()
    row = db.get(Invoice, inv["id"])
    row.created_at = row.created_at - DAY
    db.commit()
    r = client.post(f"/api/invoices/{inv['id']}/cancel", json={"reason": "Lập sai hóa đơn"}, headers=owner_h)
    assert r.status_code == 409 and "trong ngày lập" in r.json()["detail"]


# ---------------------------------------------------------------- In ấn
# TC-PAY-03 (SRS 11.3)
def test_invoice_pdf_and_reprint(client, staff_h, owner_h, sample):
    inv = sell(client, staff_h, sample["items"], customer_id=sample["customer"]["id"]).json()
    first = client.get(f"/api/invoices/{inv['id']}/pdf", headers=staff_h)
    assert first.status_code == 200 and first.content.startswith(b"%PDF")
    again = client.get(f"/api/invoices/{inv['id']}/pdf", headers=staff_h)
    assert again.status_code == 200
    assert client.get(f"/api/invoices/{inv['id']}", headers=staff_h).json()["print_count"] == 2
    logs = client.get("/api/audit-logs", params={"action": "INVOICE_REPRINT"}, headers=owner_h).json()
    assert logs["total"] == 1


def test_email_invoice_requires_customer_email(client, staff_h, sample):
    inv = sell(client, staff_h, sample["items"][:1], customer_id=sample["customer"]["id"]).json()
    r = client.post(f"/api/invoices/{inv['id']}/email", headers=staff_h)
    assert r.status_code == 400 and "email" in r.json()["detail"]


def test_list_masks_phone_detail_shows_full(client, staff_h, sample):
    inv = sell(client, staff_h, sample["items"][:1], customer_id=sample["customer"]["id"]).json()
    listed = client.get("/api/invoices", headers=staff_h).json()["items"][0]
    assert listed["customer_phone"] == "0912 *** 678"
    assert client.get(f"/api/invoices/{inv['id']}", headers=staff_h).json()["customer_phone"] == "0912345678"
    customers = client.get("/api/customers", headers=staff_h).json()["items"]
    assert customers[0]["phone"] == "0912 *** 678"
