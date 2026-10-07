"""Test chuông thông báo: mỗi vai trò chỉ thấy việc thuộc phạm vi của mình."""
from tests.helpers import product_id


def kinds(client, h):
    r = client.get("/api/notifications", headers=h)
    assert r.status_code == 200, r.text
    return {i["type"]: i for i in r.json()["items"]}


def test_low_stock_and_cancel_request_by_role(client, staff_h, owner_h, admin_h):
    # Dữ liệu mẫu: PK002 tồn 0 nhỏ hơn mức tối thiểu 5
    low = kinds(client, staff_h)["low_stock"]
    assert low["count"] == 1 and low["names"] == ["Tai nghe Bluetooth A2 Pro (0)"]

    pk1 = product_id(client, staff_h, "PK001")
    inv = client.post("/api/invoices", json={"items": [{"product_id": pk1, "quantity": 1}]}, headers=staff_h).json()
    client.post(f"/api/invoices/{inv['id']}/cancel", json={"reason": "Bấm nhầm sản phẩm"}, headers=staff_h)
    cancel = kinds(client, owner_h)["cancel_requests"]
    assert cancel["count"] == 1 and cancel["names"] == [inv["code"]] and cancel["latest_at"]
    assert "cancel_requests" not in kinds(client, staff_h)  # chỉ chủ cửa hàng duyệt hủy

    # Quản trị viên không thấy tồn kho, hóa đơn
    assert not {"low_stock", "cancel_requests", "pending_payment"} & set(kinds(client, admin_h))


def test_admin_sees_pending_registration(client, admin_h, owner_h):
    client.post("/api/auth/register", json={"username": "nguyenvanan", "full_name": "Nguyễn Văn An", "password": "matkhau123"})
    pending = kinds(client, admin_h)["pending_users"]
    assert pending["count"] == 1 and pending["names"] == ["Nguyễn Văn An"]
    assert "pending_users" not in kinds(client, owner_h)


def test_requires_login(client):
    assert client.get("/api/notifications").status_code == 401



def test_ai_prompt_follows_interface_language():
    """Giao diện tiếng Anh (header Accept-Language: en, middleware đặt reply_lang) thì prompt dặn AI trả lời tiếng Anh."""
    from app.ai.client import ENGLISH_NOTE, localize, reply_lang

    assert localize("Bạn là trợ lý") == "Bạn là trợ lý"
    token = reply_lang.set("en")
    try:
        assert localize("Bạn là trợ lý") == "Bạn là trợ lý" + ENGLISH_NOTE
    finally:
        reply_lang.reset(token)


def test_english_names_for_products_and_categories(client, owner_h, staff_h):
    """Tên tiếng Anh (name_en) nhập ở form sản phẩm / nhóm hàng; giao diện tiếng Anh lấy bảng tên qua /api/catalog/names."""
    cat = client.post("/api/categories", json={"name": "Loa", "name_en": "  Speakers "}, headers=owner_h).json()
    assert cat["name_en"] == "Speakers"
    p = client.post("/api/products", json={"code": "LO-01", "name": "Loa bluetooth mini", "name_en": "Mini Bluetooth Speaker",
                                           "category_id": cat["id"], "sale_price": 300_000}, headers=owner_h).json()
    assert p["name_en"] == "Mini Bluetooth Speaker"
    names = client.get("/api/catalog/names", headers=staff_h).json()
    assert names["Loa"] == "Speakers" and names["Loa bluetooth mini"] == "Mini Bluetooth Speaker"
    assert "Sạc nhanh 20W" not in names  # sản phẩm chưa có tên tiếng Anh thì không có trong bảng
    # Tìm sản phẩm bằng tên tiếng Anh, xóa tên tiếng Anh bằng chuỗi rỗng
    assert [x["code"] for x in client.get("/api/products", params={"q": "bluetooth speaker"}, headers=staff_h).json()["items"]] == ["LO-01"]
    client.put(f"/api/products/{p['id']}", json={"name_en": ""}, headers=owner_h)
    assert "Loa bluetooth mini" not in client.get("/api/catalog/names", headers=staff_h).json()


def test_paid_orders_notify_owner_and_cashier(client, owner_h, staff_h):
    pid = product_id(client, staff_h, "PK001")
    assert "payments" not in kinds(client, owner_h)
    inv = client.post("/api/invoices", json={"items": [{"product_id": pid, "quantity": 2}]}, headers=staff_h).json()
    pay = kinds(client, owner_h)["payments"]
    assert pay["count"] == 1 and pay["amount"] == inv["total"] and pay["latest_at"]
    assert pay["details"][0]["code"] == inv["code"] and pay["details"][0]["method"] == "cash"
    assert kinds(client, staff_h)["payments"]["count"] == 1
    # Đơn của chủ cửa hàng: nhân viên không thấy, chủ cửa hàng thấy cả hai
    client.post("/api/invoices", json={"items": [{"product_id": pid, "quantity": 1}]}, headers=owner_h)
    assert kinds(client, owner_h)["payments"]["count"] == 2
    assert kinds(client, staff_h)["payments"]["count"] == 1
