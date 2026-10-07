from tests.helpers import product_id


_phones = iter(f"09{n:08d}" for n in range(10_000_000, 99_999_999))


def new_customer(client, h, **kw):
    r = client.post("/api/customers", json={"name": "Khách thử", "phone": next(_phones), **kw}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


# FR-CUS-01
def test_staff_can_edit_customer(client, staff_h):
    c = new_customer(client, staff_h, phone="0911111111")
    r = client.put(f"/api/customers/{c['id']}", json={"name": "Khách đã sửa", "phone": "0922222222", "group": "vip"},
                   headers=staff_h)
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Khách đã sửa" and r.json()["phone"] == "0922222222" and r.json()["group"] == "vip"
    assert r.json()["code"] == c["code"]


def test_edit_rejects_phone_of_another_customer(client, owner_h):
    c = new_customer(client, owner_h)
    r = client.put(f"/api/customers/{c['id']}", json={"name": "Khách thử", "phone": "0901234567"}, headers=owner_h)
    assert r.status_code == 400 and "đã được đăng ký" in r.text


def test_manager_deletes_customer_without_invoices(client, owner_h, staff_h):
    c = new_customer(client, owner_h)
    assert client.delete(f"/api/customers/{c['id']}", headers=staff_h).status_code == 403
    assert client.delete(f"/api/customers/{c['id']}", headers=owner_h).status_code == 200
    assert client.get(f"/api/customers/{c['id']}", headers=owner_h).status_code == 404


def test_cannot_delete_customer_with_invoices(client, owner_h):
    c = new_customer(client, owner_h)
    pk1 = product_id(client, owner_h, "PK001")
    r = client.post("/api/invoices", json={"items": [{"product_id": pk1, "quantity": 1}], "customer_id": c["id"]},
                    headers=owner_h)
    assert r.status_code == 201, r.text
    r = client.delete(f"/api/customers/{c['id']}", headers=owner_h)
    assert r.status_code == 400 and "đã có hóa đơn" in r.text


# FR-CUS-01, BR-40
def test_phone_must_be_10_digits_starting_with_0(client, owner_h):
    for phone in ("4358475875845", "901234567", "09012345678", "1901234567", "09012a4567", "+84901234567"):
        r = client.post("/api/customers", json={"name": "Khách thử", "phone": phone}, headers=owner_h)
        assert r.status_code == 422, phone
        assert "10 chữ số, bắt đầu bằng 0" in r.text


def test_valid_phone_is_normalized(client, owner_h):
    r = client.post("/api/customers", json={"name": "Khách thử", "phone": "091 234.5678"}, headers=owner_h)
    assert r.status_code in (200, 201)
    assert r.json()["phone"] == "0912345678"
    r = client.post("/api/customers", json={"name": "Không SĐT", "phone": ""}, headers=owner_h)
    assert r.status_code == 422  # FR-CUS-02: số điện thoại bắt buộc
