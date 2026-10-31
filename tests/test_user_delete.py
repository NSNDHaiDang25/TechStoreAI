"""Xóa tài khoản: chưa có lịch sử thì xóa hẳn; đã có lịch sử thì gỡ khỏi hệ thống nhưng giữ tên trên hóa đơn cũ."""
from tests.conftest import _login


def users(client, admin_h):
    return {u["username"]: u for u in client.get("/api/users", headers=admin_h).json()}


def test_account_without_history_is_removed_completely(client, admin_h, branch_id, db):
    from app.models import User
    r = client.post("/api/users", json={"username": "nvmoi", "full_name": "NV Mới", "password": "Matkhau123",
                                        "role": "staff", "branch_id": branch_id}, headers=admin_h)
    uid = r.json()["id"]
    r = client.delete(f"/api/users/{uid}", headers=admin_h)
    assert r.status_code == 200 and r.json()["deleted"] is True
    db.expire_all()
    assert db.get(User, uid) is None
    assert "nvmoi" not in users(client, admin_h)
    actions = [i["action"] for i in client.get("/api/audit-logs", headers=admin_h).json()["items"]]
    assert "USER_DELETE" in actions


def test_account_with_history_is_hidden_but_invoices_keep_the_name(client, admin_h, owner_h, staff_h, branch_id):
    pid = client.get("/api/products", params={"q": "PK001"}, headers=staff_h).json()["items"][0]["id"]
    inv = client.post("/api/invoices", json={"items": [{"product_id": pid, "quantity": 1}]}, headers=staff_h).json()
    staff = users(client, admin_h)["staff"]
    r = client.delete(f"/api/users/{staff['id']}", headers=admin_h)
    assert r.status_code == 200 and r.json()["deleted"] is False
    assert "staff" not in users(client, admin_h)  # ẩn khỏi danh sách
    assert client.post("/api/auth/login", json={"username": "staff", "password": "staff123"}).status_code == 401
    assert client.get("/api/products", headers=staff_h).status_code == 401  # phiên đang mở cũng hết hiệu lực
    # Hóa đơn cũ vẫn ghi đúng người lập
    assert client.get(f"/api/invoices/{inv['id']}", headers=owner_h).json()["user_name"] == "Nhân viên"
    # Tên đăng nhập được dùng lại cho tài khoản mới
    r = client.post("/api/users", json={"username": "staff", "full_name": "NV thay thế", "password": "Matkhau123",
                                        "role": "staff", "branch_id": branch_id}, headers=admin_h)
    assert r.status_code == 201, r.text
    assert _login(client, "staff", "Matkhau123")


def test_cannot_delete_self_or_last_admin(client, admin_h, owner_h):
    me = users(client, admin_h)["admin"]
    assert client.delete(f"/api/users/{me['id']}", headers=admin_h).status_code == 400
    assert client.delete(f"/api/users/{me['id']}", headers=owner_h).status_code == 403
    assert client.delete("/api/users/9999", headers=admin_h).status_code == 404
