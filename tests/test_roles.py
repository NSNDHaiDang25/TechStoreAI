"""Phân quyền theo SRS bảng 4.2: ba vai trò độc lập, không kế thừa quyền của nhau.

Quản trị viên quản trị hệ thống (tài khoản, cấu hình kỹ thuật và AI, sao lưu, nhật ký) nhưng không bán hàng,
không xem giá vốn và doanh thu. Chủ cửa hàng không tự thêm tài khoản, không sao lưu.
"""
import pytest

from tests.helpers import product_id

# Nghiệp vụ bán hàng, hàng hóa, báo cáo, AI nghiệp vụ: quản trị viên không vào được
BUSINESS = [
    ("get", "/api/products"), ("get", "/api/customers"), ("get", "/api/invoices"),
    ("get", "/api/reports/dashboard"), ("get", "/api/reports/revenue"), ("get", "/api/reports/inventory"),
    ("get", "/api/purchase-orders"), ("get", "/api/suppliers"), ("get", "/api/promotions"),
    ("get", "/api/inventory/low-stock"), ("get", "/api/inventory/movements"), ("get", "/api/warranty-tickets"),
    ("post", "/api/ai/assistant"), ("post", "/api/ai/advisor"), ("post", "/api/ai/report"), ("post", "/api/ai/ask"),
]
# Quản trị hệ thống: chủ cửa hàng và nhân viên không vào được
ADMIN = [("get", "/api/users"), ("post", "/api/admin/backup")]
# Quản trị viên và chủ cửa hàng (mỗi bên thấy phần của mình), nhân viên không vào được
ADMIN_AND_OWNER = [("get", "/api/audit-logs"), ("get", "/api/email-logs")]


def call(client, method, url, h):
    body = {"message": "xin chào", "question": "doanh thu hôm nay"} if method == "post" else None
    return getattr(client, method)(url, headers=h, **({"json": body} if body else {}))


# FR-AUT-08 (SRS 4.2)
@pytest.mark.parametrize("method,url", BUSINESS)
def test_admin_has_no_business_access(client, admin_h, method, url):
    assert call(client, method, url, admin_h).status_code == 403


# FR-AUT-08 (SRS 4.2)
@pytest.mark.parametrize("method,url", ADMIN)
def test_owner_and_staff_have_no_admin_access(client, owner_h, staff_h, method, url):
    assert call(client, method, url, owner_h).status_code == 403
    assert call(client, method, url, staff_h).status_code == 403


# FR-AUT-08 (SRS 4.2)
@pytest.mark.parametrize("method,url", ADMIN_AND_OWNER)
def test_logs_for_admin_and_owner_only(client, admin_h, owner_h, staff_h, method, url):
    assert call(client, method, url, admin_h).status_code == 200
    assert call(client, method, url, owner_h).status_code == 200
    assert call(client, method, url, staff_h).status_code == 403


# FR-AUT-08 (SRS 4.2)
def test_admin_cannot_sell(client, admin_h, owner_h):
    pid = product_id(client, owner_h, "PK001")
    r = client.post("/api/invoices", json={"items": [{"product_id": pid, "quantity": 1}],
                                           "payment_method": "cash"}, headers=admin_h)
    assert r.status_code == 403


# FR-AUT-08 (SRS 4.2)
def test_admin_sees_ai_status_and_logs(client, admin_h):
    assert client.get("/api/ai/status", headers=admin_h).status_code == 200
    assert client.get("/api/ai/logs", headers=admin_h).status_code == 200


# FR-AUT-08 (SRS 4.2)
def test_settings_split_by_role(client, admin_h, owner_h):
    """Bảng 2.5: chủ cửa hàng sửa tham số kinh doanh, quản trị viên sửa tham số kỹ thuật và AI."""
    assert client.put("/api/settings", json={"values": {"ai_enabled": False}}, headers=owner_h).status_code == 403
    assert client.put("/api/settings", json={"values": {"low_stock_threshold": 7}}, headers=admin_h).status_code == 403
    assert client.put("/api/settings", json={"values": {"low_stock_threshold": 7}}, headers=owner_h).status_code == 200
    assert client.put("/api/settings", json={"values": {"ai_timeout_seconds": 25}}, headers=admin_h).status_code == 200
