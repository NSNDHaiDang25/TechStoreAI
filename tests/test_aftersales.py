"""Đổi trả trong 24 giờ và bảo hành theo SRS (bộ số mẫu mục 3.4)."""
from datetime import timedelta

from app.models import Invoice, Promotion, Warranty, now
from tests.helpers import stock_of
from tests.test_sales import add_product, phone_with_serials, sample, sell  # noqa: F401 (fixture dùng chung)


def checkout_sample(client, h, sample, **kw):
    r = sell(client, h, sample["items"], customer_id=sample["customer"]["id"], promo_code="TECH10",
             points_used=200, **kw)
    assert r.status_code == 201, r.text
    return r.json()


def line(inv, code):
    return next(it for it in inv["items"] if it["product_code"] == code)


# ---------------------------------------------------------------- Đổi trả
# TC-RET-01 (SRS 11.3)
def test_return_headset_matches_srs_example(client, staff_h, owner_h, sample):
    """SRS 3.4: trả tai nghe trong 24 giờ hoàn 1.155.831 đồng, trừ 138 điểm, điểm đã dùng không hoàn."""
    inv = checkout_sample(client, staff_h, sample)
    head = line(inv, "TN-CH520")
    elig = client.get(f"/api/returns/eligible/{inv['id']}", headers=staff_h).json()
    assert elig["eligible"] and 0 < elig["seconds_left"] <= 24 * 3600
    r = client.post("/api/returns", json={"invoice_id": inv["id"], "reason": "Khách đổi ý không dùng",
                                         "items": [{"invoice_item_id": head["id"], "quantity": 1}]}, headers=staff_h)
    assert r.status_code == 201, r.text
    ret = r.json()
    assert ret["code"].startswith("DT-") and ret["refund_amount"] == 1_155_831 and ret["points_reversed"] == 138
    assert ret["refund_method"] == "cash"
    c = client.get(f"/api/customers/{sample['customer']['id']}", headers=staff_h).json()
    assert c["loyalty_points"] == 2_330 - 138
    assert c["total_spent"] == 25_000_000 + 17_590_000 - 1_155_831
    assert client.get(f"/api/invoices/{inv['id']}", headers=staff_h).json()["status"] == "partially_returned"
    assert stock_of(client, staff_h, "TN-CH520") == 20  # sellable: nhập lại kho
    # Báo cáo: tiền hoàn trừ vào doanh thu ngày đổi trả (FR-RPT-06)
    s = client.get("/api/reports/revenue", params={"date_from": now().date().isoformat()}, headers=owner_h).json()
    assert s["summary"]["refunds"] == 1_155_831 and s["summary"]["revenue"] == 17_590_000 - 1_155_831


# TC-RET-05 (SRS 11.3)
def test_cannot_return_more_than_bought_or_twice(client, staff_h, sample):
    inv = checkout_sample(client, staff_h, sample)
    mouse = line(inv, "CH-M331")
    body = {"invoice_id": inv["id"], "reason": "Khách đổi ý không dùng"}
    too_many = client.post("/api/returns", json={**body, "items": [{"invoice_item_id": mouse["id"], "quantity": 3}]},
                           headers=staff_h)
    assert too_many.status_code == 409 and "tối đa 2" in too_many.json()["detail"]
    a = client.post("/api/returns", json={**body, "items": [{"invoice_item_id": mouse["id"], "quantity": 1}]},
                    headers=staff_h).json()
    b = client.post("/api/returns", json={**body, "items": [{"invoice_item_id": mouse["id"], "quantity": 1}]},
                    headers=staff_h).json()
    assert a["refund_amount"] + b["refund_amount"] == 563_346  # lũy kế đúng cột 'Còn lại'
    again = client.post("/api/returns", json={**body, "items": [{"invoice_item_id": mouse["id"], "quantity": 1}]},
                        headers=staff_h)
    assert again.status_code == 409


# TC-RET-02 (SRS 11.3)
def test_return_window_and_status_rules(client, staff_h, sample, db):
    pending = sell(client, staff_h, sample["items"][:1], payment_method="bank_transfer").json()
    r = client.get(f"/api/returns/eligible/{pending['id']}", headers=staff_h).json()
    assert not r["eligible"] and "chưa thanh toán" in r["reason"]
    inv = sell(client, staff_h, sample["items"][:1]).json()
    row = db.get(Invoice, inv["id"])
    row.paid_at = now() - timedelta(hours=25)
    db.commit()
    r = client.post("/api/returns", json={"invoice_id": inv["id"], "reason": "Máy bị lỗi màn hình",
                                         "items": [{"invoice_item_id": inv["items"][0]["id"], "quantity": 1}]},
                    headers=staff_h)
    assert r.status_code == 409 and "bảo hành" in r.json()["detail"]


# TC-RET-04 (SRS 11.3)
def test_defective_return_does_not_restock(client, staff_h, sample):
    inv = sell(client, staff_h, sample["items"][3:4]).json()
    assert stock_of(client, staff_h, "SAC-ANKER20") == 19
    client.post("/api/returns", json={"invoice_id": inv["id"], "reason": "Sạc không vào điện",
                                     "items": [{"invoice_item_id": inv["items"][0]["id"], "quantity": 1,
                                                "item_condition": "defective"}]}, headers=staff_h)
    assert stock_of(client, staff_h, "SAC-ANKER20") == 19  # BR-33
    assert client.get(f"/api/invoices/{inv['id']}", headers=staff_h).json()["status"] == "fully_returned"


def test_full_return_releases_voucher_and_voids_warranty(client, staff_h, sample, db):
    inv = sell(client, staff_h, sample["items"][:1], promo_code="TECH10").json()
    client.post("/api/returns", json={"invoice_id": inv["id"], "reason": "Khách đổi ý không mua",
                                     "items": [{"invoice_item_id": inv["items"][0]["id"], "quantity": 1}]},
                headers=staff_h)
    promo = db.query(Promotion).filter_by(code="TECH10").one()
    db.refresh(promo)
    assert promo.used_count == 0  # BR-09
    w = db.query(Warranty).filter_by(invoice_item_id=inv["items"][0]["id"]).one()
    db.refresh(w)
    assert w.status == "void"  # BR-37


# TC-RET-03 (SRS 11.3)
def test_serial_must_match_and_returns_to_stock(client, staff_h, phone_with_serials):
    pid = phone_with_serials["id"]
    inv = sell(client, staff_h, [{"product_id": pid, "quantity": 1, "serial_no": "IMEI0000001"}]).json()
    item = inv["items"][0]["id"]
    body = {"invoice_id": inv["id"], "reason": "Khách đổi ý không mua"}
    wrong = client.post("/api/returns", json={**body, "items": [{"invoice_item_id": item, "quantity": 1,
                                                               "serial_no": "IMEI0000002"}]}, headers=staff_h)
    assert wrong.status_code == 409 and "không khớp" in wrong.json()["detail"]
    ok = client.post("/api/returns", json={**body, "items": [{"invoice_item_id": item, "quantity": 1,
                                                            "serial_no": "imei0000001"}]}, headers=staff_h)
    assert ok.status_code == 201
    serials = {s["serial_no"]: s["status"] for s in client.get(f"/api/products/{pid}/serials", headers=staff_h).json()}
    assert serials["IMEI0000001"] == "in_stock" and stock_of(client, staff_h, "DT-IP15") == 2


def test_exchange_creates_new_invoice(client, staff_h, sample):
    p = sample["products"]
    inv = sell(client, staff_h, [{"product_id": p["mouse"]["id"], "quantity": 1}]).json()
    r = client.post("/api/returns", json={
        "invoice_id": inv["id"], "reason": "Đổi sang tai nghe",
        "items": [{"invoice_item_id": inv["items"][0]["id"], "quantity": 1}],
        "exchange_items": [{"product_id": p["headset"]["id"], "quantity": 1}]}, headers=staff_h)
    assert r.status_code == 201, r.text
    ret = r.json()
    assert ret["return_type"] == "exchange" and ret["new_invoice_code"].startswith("HD-")
    assert ret["customer_pays"] == 1_190_000 - 290_000 and ret["store_pays"] == 0
    assert stock_of(client, staff_h, "TN-CH520") == 19 and stock_of(client, staff_h, "CH-M331") == 20


def test_cancel_not_allowed_after_return(client, owner_h, sample):
    inv = sell(client, owner_h, sample["items"][1:2]).json()
    client.post("/api/returns", json={"invoice_id": inv["id"], "reason": "Khách đổi ý không mua",
                                     "items": [{"invoice_item_id": inv["items"][0]["id"], "quantity": 1}]},
                headers=owner_h)
    r = client.post(f"/api/invoices/{inv['id']}/cancel", json={"reason": "Lập sai hóa đơn"}, headers=owner_h)
    assert r.status_code == 409 and "đổi trả" in r.json()["detail"]


# FR-RET-01
def test_lookup_by_phone_and_print_slip(client, staff_h, sample):
    inv = checkout_sample(client, staff_h, sample)
    found = client.get("/api/returns/lookup", params={"q": "0912345678"}, headers=staff_h).json()
    assert [f["code"] for f in found] == [inv["code"]]
    ret = client.post("/api/returns", json={"invoice_id": inv["id"], "reason": "Khách đổi ý không dùng",
                                           "items": [{"invoice_item_id": line(inv, "SAC-ANKER20")["id"],
                                                      "quantity": 1}]}, headers=staff_h).json()
    pdf = client.get(f"/api/returns/{ret['id']}/pdf", headers=staff_h)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert client.get("/api/returns", headers=staff_h).json()["refund_total"] == 339_951


# ---------------------------------------------------------------- Bảo hành
# TC-WAR-02, TC-WAR-04 (SRS 11.3)
def test_warranty_lookup_and_ticket_lifecycle(client, staff_h, phone_with_serials, sample):
    pid = phone_with_serials["id"]
    sell(client, staff_h, [{"product_id": pid, "quantity": 1, "serial_no": "IMEI0000002"}],
         customer_id=sample["customer"]["id"])
    for q in ("IMEI0000002", "0912345678"):
        found = client.get("/api/warranties/lookup", params={"q": q}, headers=staff_h).json()
        assert len(found) == 1 and found[0]["can_receive"], q
    w = found[0]
    assert w["status"] == "active" and w["days_left"] >= 365
    t = client.post("/api/warranty-tickets", json={"warranty_id": w["id"], "issue_description": "Không lên nguồn"},
                    headers=staff_h)
    assert t.status_code == 201, t.text
    ticket = t.json()
    assert ticket["code"].startswith("BH-") and ticket["status"] == "received"
    dup = client.post("/api/warranty-tickets", json={"warranty_id": w["id"], "issue_description": "Lỗi thứ hai"},
                      headers=staff_h)
    assert dup.status_code == 409 and ticket["code"] in dup.json()["detail"]  # FR-WAR-04
    serial = next(s for s in client.get(f"/api/products/{pid}/serials", headers=staff_h).json()
                  if s["serial_no"] == "IMEI0000002")
    assert serial["status"] == "in_warranty"

    def move(status, resolution=None):
        return client.put(f"/api/warranty-tickets/{ticket['id']}", json={"status": status, "resolution": resolution},
                          headers=staff_h)

    assert move("returned").status_code == 409  # sai thứ tự
    assert move("in_repair").json()["status"] == "in_repair"
    assert move("done").status_code == 409  # thiếu kết quả xử lý
    assert move("done", "Thay IC nguồn").json()["completed_at"]
    assert move("returned").json()["returned_at"]
    serial = next(s for s in client.get(f"/api/products/{pid}/serials", headers=staff_h).json()
                  if s["serial_no"] == "IMEI0000002")
    assert serial["status"] == "sold"
    pdf = client.get(f"/api/warranty-tickets/{ticket['id']}/pdf", headers=staff_h)
    assert pdf.content.startswith(b"%PDF")
    # Máy đã trả khách: nhận bảo hành lần sau được
    assert client.post("/api/warranty-tickets", json={"warranty_id": w["id"], "issue_description": "Lỗi loa ngoài"},
                       headers=staff_h).status_code == 201


# TC-WAR-03 (SRS 11.3)
def test_expired_or_void_warranty_cannot_be_received(client, staff_h, sample, db):
    inv = sell(client, staff_h, sample["items"][:1]).json()
    w = db.query(Warranty).filter_by(invoice_item_id=inv["items"][0]["id"]).one()
    w.end_date = now().date() - timedelta(days=1)
    db.commit()
    r = client.post("/api/warranty-tickets", json={"warranty_id": w.id, "issue_description": "Hỏng bàn phím"},
                    headers=staff_h)
    assert r.status_code == 409 and "hết hạn" in r.json()["detail"]
