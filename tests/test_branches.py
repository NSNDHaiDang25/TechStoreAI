"""Chi nhánh: quản trị viên tạo chi nhánh, gán chủ cửa hàng / nhân viên, xem nhật ký thao tác tách theo chi nhánh."""
from tests.conftest import _login


def make_branch(client, admin_h, name):
    r = client.post("/api/branches", json={"name": name, "address": f"{name} - địa chỉ"}, headers=admin_h)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def user_id(client, admin_h, username):
    return next(u["id"] for u in client.get("/api/users", headers=admin_h).json() if u["username"] == username)


def change_price(client, h, code, price):
    pid = client.get("/api/products", params={"q": code}, headers=h).json()["items"][0]["id"]
    r = client.put(f"/api/products/{pid}", json={"sale_price": price}, headers=h)
    assert r.status_code == 200, r.text


def logs(client, h, **params):
    return client.get("/api/audit-logs", params=params, headers=h).json()


def test_admin_manages_branches(client, admin_h, owner_h):
    bid = make_branch(client, admin_h, "Cơ sở Cầu Giấy")
    assert client.post("/api/branches", json={"name": "cơ sở cầu giấy"}, headers=admin_h).status_code == 400  # trùng tên
    r = client.put(f"/api/branches/{bid}", json={"name": "Cơ sở 1", "is_active": True}, headers=admin_h)
    assert r.json()["name"] == "Cơ sở 1"
    assert client.get("/api/branches", headers=owner_h).status_code == 403
    actions = [i["action"] for i in logs(client, admin_h)["items"]]
    assert "BRANCH_CREATE" in actions and "BRANCH_UPDATE" in actions


def test_actions_are_logged_under_the_branch_of_the_user(client, admin_h, owner_h):
    a = make_branch(client, admin_h, "Cơ sở A")
    b = make_branch(client, admin_h, "Cơ sở B")
    owner_id = user_id(client, admin_h, "owner")
    change_price(client, owner_h, "PK001", 360_000)  # trước khi gán chi nhánh
    r = client.put(f"/api/users/{owner_id}", json={"branch_id": a}, headers=admin_h)
    assert r.status_code == 200 and r.json()["branch_name"] == "Cơ sở A"
    change_price(client, owner_h, "PK001", 370_000)
    # chủ cửa hàng thứ hai ở cơ sở B
    r = client.post("/api/users", json={"username": "owner2", "full_name": "Chủ B", "password": "Owner2pass",
                                        "role": "owner", "branch_id": b}, headers=admin_h)
    assert r.status_code == 201 and r.json()["branch_id"] == b
    owner2_h = _login(client, "owner2", "Owner2pass")
    change_price(client, owner2_h, "PK003", 200_000)

    in_a = logs(client, admin_h, branch_id=a, action="PRICE_CHANGE")["items"]
    in_b = logs(client, admin_h, branch_id=b, action="PRICE_CHANGE")["items"]
    assert len(in_a) == 2  # lần gán chi nhánh đầu tiên: thao tác cũ của người đó cũng tính vào cơ sở A
    assert [i["branch_name"] for i in in_b] == ["Cơ sở B"] and "200000" in in_b[0]["new_value"]
    # mỗi chủ cửa hàng chỉ thấy nhật ký chi nhánh mình, kể cả khi cố lọc chi nhánh khác
    mine = logs(client, owner2_h, branch_id=a)
    assert {i["branch_name"] for i in mine["items"]} == {"Cơ sở B"} and mine["branch_name"] == "Cơ sở B"
    assert mine["branches"] == []
    assert {x["name"] for x in logs(client, admin_h)["branches"]} == {"Cơ sở A", "Cơ sở B"}


def test_admin_actions_on_an_account_go_to_that_accounts_branch(client, admin_h):
    a = make_branch(client, admin_h, "Cơ sở A")
    staff_id = user_id(client, admin_h, "staff")
    client.put(f"/api/users/{staff_id}", json={"branch_id": a}, headers=admin_h)
    client.post(f"/api/users/{staff_id}/reset-password", json={"new_password": "Newpass123"}, headers=admin_h)
    client.post("/api/auth/login", json={"username": "staff", "password": "sai-mat-khau1"})
    actions = {i["action"] for i in logs(client, admin_h, branch_id=a)["items"]}
    assert {"USER_UPDATE", "PASSWORD_RESET", "LOGIN_FAILED"} <= actions
    # thao tác hệ thống của quản trị viên (tạo chi nhánh) không thuộc chi nhánh nào
    assert "BRANCH_CREATE" in {i["action"] for i in logs(client, admin_h, branch_id=0)["items"]}


def test_admin_has_no_branch_and_branch_must_be_active(client, admin_h):
    a = make_branch(client, admin_h, "Cơ sở A")
    r = client.post("/api/users", json={"username": "admin2", "full_name": "QTV 2", "password": "Admin2pass",
                                        "role": "admin", "branch_id": a}, headers=admin_h)
    assert r.status_code == 201 and r.json()["branch_id"] is None
    client.put(f"/api/branches/{a}", json={"name": "Cơ sở A", "is_active": False}, headers=admin_h)
    r = client.post("/api/users", json={"username": "staff2", "full_name": "NV 2", "password": "Staff2pass",
                                        "role": "staff", "branch_id": a}, headers=admin_h)
    assert r.status_code == 400
    staff_id = user_id(client, admin_h, "staff")
    assert client.put(f"/api/users/{staff_id}", json={"branch_id": 999}, headers=admin_h).status_code == 400
