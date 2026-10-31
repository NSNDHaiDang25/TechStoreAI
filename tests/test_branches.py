"""Chi nhánh: quản trị viên tạo chi nhánh, gán chủ cửa hàng / nhân viên; mỗi chi nhánh độc lập, không thấy dữ liệu
của nhau; nhật ký thao tác tách theo chi nhánh."""
from app.models import Product
from tests.conftest import _login


def make_branch(client, admin_h, name):
    r = client.post("/api/branches", json={"name": name, "address": f"{name} - địa chỉ"}, headers=admin_h)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def make_user(client, admin_h, username, role, branch):
    r = client.post("/api/users", json={"username": username, "full_name": username.upper(), "password": "Matkhau123",
                                        "role": role, "branch_id": branch}, headers=admin_h)
    assert r.status_code == 201, r.text
    return _login(client, username, "Matkhau123")


def user_id(client, admin_h, username):
    return next(u["id"] for u in client.get("/api/users", headers=admin_h).json() if u["username"] == username)


def change_price(client, h, code, price):
    pid = client.get("/api/products", params={"q": code}, headers=h).json()["items"][0]["id"]
    r = client.put(f"/api/products/{pid}", json={"sale_price": price}, headers=h)
    assert r.status_code == 200, r.text


def logs(client, h, **params):
    return client.get("/api/audit-logs", params=params, headers=h).json()


def new_product(client, h, code, price=100_000, **extra):
    return client.post("/api/products", json={"code": code, "name": f"SP {code}", "sale_price": price, **extra}, headers=h)


def test_admin_manages_branches(client, admin_h, owner_h):
    bid = make_branch(client, admin_h, "Cơ sở Cầu Giấy")
    assert client.post("/api/branches", json={"name": "cơ sở cầu giấy"}, headers=admin_h).status_code == 400  # trùng tên
    r = client.put(f"/api/branches/{bid}", json={"name": "Cơ sở 1", "is_active": True}, headers=admin_h)
    assert r.json()["name"] == "Cơ sở 1"
    assert client.get("/api/branches", headers=owner_h).status_code == 403
    actions = [i["action"] for i in logs(client, admin_h)["items"]]
    assert "BRANCH_CREATE" in actions and "BRANCH_UPDATE" in actions


# ---------------- Mỗi chi nhánh độc lập ----------------
def test_branches_do_not_see_each_others_data(client, admin_h, owner_h, staff_h, db):
    b = make_branch(client, admin_h, "Cơ sở B")
    owner_b = make_user(client, admin_h, "chub", "owner", b)
    staff_b = make_user(client, admin_h, "nvb", "staff", b)

    # Sản phẩm, khách hàng của chi nhánh chính không hiện ở cơ sở B và ngược lại
    assert client.get("/api/products", headers=owner_b).json()["total"] == 0
    assert client.get("/api/customers", headers=staff_b).json()["total"] == 0
    assert new_product(client, owner_b, "B-001", 200_000, stock=5).status_code == 201
    r = client.post("/api/customers", json={"name": "Khách B", "phone": "0909000111"}, headers=staff_b)
    assert r.status_code == 201, r.text
    assert [p["code"] for p in client.get("/api/products", headers=owner_b).json()["items"]] == ["B-001"]
    assert "B-001" not in {p["code"] for p in client.get("/api/products", headers=owner_h).json()["items"]}
    assert "Khách B" not in {c["name"] for c in client.get("/api/customers", headers=staff_h).json()["items"]}

    # Không mở được bản ghi của chi nhánh khác bằng id
    pk001 = client.get("/api/products", params={"q": "PK001"}, headers=owner_h).json()["items"][0]["id"]
    assert client.get(f"/api/products/{pk001}", headers=owner_b).status_code == 404
    assert client.put(f"/api/products/{pk001}", json={"sale_price": 1}, headers=owner_b).status_code == 404

    # Bán hàng ở cơ sở B: hóa đơn, tồn kho, báo cáo chỉ của cơ sở B
    bid = client.get("/api/products", headers=owner_b).json()["items"][0]["id"]
    inv = client.post("/api/invoices", json={"items": [{"product_id": bid, "quantity": 1}]}, headers=staff_b)
    assert inv.status_code == 201, inv.text
    assert [i["code"] for i in client.get("/api/invoices", headers=owner_h).json()["items"]] == []
    assert len(client.get("/api/invoices", headers=owner_b).json()["items"]) == 1
    assert client.get(f"/api/invoices/{inv.json()['id']}", headers=owner_h).status_code == 404
    rev_main = client.get("/api/reports/revenue", headers=owner_h).json()
    rev_b = client.get("/api/reports/revenue", headers=owner_b).json()
    assert rev_b != rev_main

    # Dữ liệu ghi xuống đúng chi nhánh
    assert db.query(Product).execution_options(all_branches=True).filter_by(code="B-001").one().branch_id == b


def test_codes_stay_unique_across_branches(client, admin_h, owner_h):
    b = make_branch(client, admin_h, "Cơ sở B")
    owner_b = make_user(client, admin_h, "chub", "owner", b)
    # SKU đã dùng ở chi nhánh khác: không tạo trùng (dù không nhìn thấy sản phẩm đó)
    assert new_product(client, owner_b, "PK001").status_code == 400
    # Mã hóa đơn sinh tiếp nối, không trùng giữa hai chi nhánh
    assert new_product(client, owner_b, "B-001", stock=5).status_code == 201
    pb = client.get("/api/products", headers=owner_b).json()["items"][0]["id"]
    pa = client.get("/api/products", params={"q": "PK001"}, headers=owner_h).json()["items"][0]["id"]
    ca = client.post("/api/invoices", json={"items": [{"product_id": pa, "quantity": 1}]}, headers=owner_h).json()["code"]
    cb = client.post("/api/invoices", json={"items": [{"product_id": pb, "quantity": 1}]}, headers=owner_b).json()["code"]
    assert ca != cb


def test_settings_are_per_branch(client, admin_h, owner_h):
    b = make_branch(client, admin_h, "Cơ sở B")
    owner_b = make_user(client, admin_h, "chub", "owner", b)
    r = client.put("/api/settings", json={"values": {"store_name": "TechStoreAI Cầu Giấy", "bank_account": "111"}},
                   headers=owner_b)
    assert r.status_code == 200, r.text
    mine = {i["key"]: i["value"] for i in client.get("/api/settings", headers=owner_b).json()["items"]}
    main = {i["key"]: i["value"] for i in client.get("/api/settings", headers=owner_h).json()["items"]}
    assert mine["store_name"] == "TechStoreAI Cầu Giấy" and mine["bank_account"] == "111"
    assert main["store_name"] != "TechStoreAI Cầu Giấy" and main["bank_account"] != "111"


def test_owner_and_staff_must_belong_to_a_branch(client, admin_h, staff_h):
    r = client.post("/api/users", json={"username": "nv9", "full_name": "NV 9", "password": "Matkhau123",
                                        "role": "staff"}, headers=admin_h)
    assert r.status_code == 400 and "chi nhánh" in r.json()["detail"]
    staff_id = user_id(client, admin_h, "staff")
    assert client.put(f"/api/users/{staff_id}", json={"branch_id": None}, headers=admin_h).status_code == 400


def test_moving_staff_to_another_branch_switches_their_data(client, admin_h, staff_h):
    b = make_branch(client, admin_h, "Cơ sở B")
    staff_id = user_id(client, admin_h, "staff")
    assert client.get("/api/products", headers=staff_h).json()["total"] == 3
    assert client.put(f"/api/users/{staff_id}", json={"branch_id": b}, headers=admin_h).status_code == 200
    assert client.get("/api/products", headers=staff_h).json()["total"] == 0  # giờ làm việc ở cơ sở B


def test_inactive_branch_cannot_sign_in(client, admin_h, branch_id):
    client.put(f"/api/branches/{branch_id}", json={"name": "Chi nhánh chính", "is_active": False}, headers=admin_h)
    r = client.post("/api/auth/login", json={"username": "staff", "password": "staff123"})
    assert r.status_code == 403 and "ngừng hoạt động" in r.json()["detail"]


# ---------------- Nhật ký thao tác theo chi nhánh ----------------
def test_actions_are_logged_under_the_branch_of_the_user(client, admin_h, owner_h, branch_id):
    b = make_branch(client, admin_h, "Cơ sở B")
    owner_b = make_user(client, admin_h, "chub", "owner", b)
    change_price(client, owner_h, "PK001", 370_000)
    assert new_product(client, owner_b, "B-001").status_code == 201
    change_price(client, owner_b, "B-001", 200_000)

    in_main = logs(client, admin_h, branch_id=branch_id, action="PRICE_CHANGE")["items"]
    in_b = logs(client, admin_h, branch_id=b, action="PRICE_CHANGE")["items"]
    assert [i["branch_name"] for i in in_main] == ["Chi nhánh chính"]
    assert [i["branch_name"] for i in in_b] == ["Cơ sở B"] and "200000" in in_b[0]["new_value"]
    # mỗi chủ cửa hàng chỉ thấy nhật ký chi nhánh mình, kể cả khi cố lọc chi nhánh khác
    mine = logs(client, owner_b, branch_id=branch_id)
    assert {i["branch_name"] for i in mine["items"]} == {"Cơ sở B"} and mine["branch_name"] == "Cơ sở B"
    assert mine["branches"] == []
    assert {x["name"] for x in logs(client, admin_h)["branches"]} == {"Chi nhánh chính", "Cơ sở B"}


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


def test_branch_detail_lists_accounts_and_counts(client, admin_h, owner_h, branch_id):
    change_price(client, owner_h, "PK001", 360_000)
    d = client.get(f"/api/branches/{branch_id}", headers=admin_h).json()
    assert [u["username"] for u in d["users"]] == ["owner", "staff"]  # chủ cửa hàng trước
    assert d["owner_count"] == 1 and d["staff_count"] == 1 and d["actions_30d"] >= 1
    assert client.get("/api/branches/999", headers=admin_h).status_code == 404
    assert client.get(f"/api/branches/{branch_id}", headers=owner_h).status_code == 403


def test_ai_sql_only_reads_own_branch(db):
    """Hỏi đáp dữ liệu (SQL do AI viết chạy trên view v_ai_*) cũng chỉ thấy dữ liệu chi nhánh của người hỏi."""
    from app.ai.text_to_sql import run_sql
    from app.models import Branch
    from app.services.branch_scope import set_scope
    other = Branch(name="Cơ sở B")
    db.add(other)
    db.flush()
    db.add(Product(code="B-001", name="Sản phẩm B", sale_price=100_000, stock=1, branch_id=other.id))
    db.commit()
    assert sorted(r[0] for r in run_sql(db, "SELECT sku FROM v_ai_products").rows) == ["PK001", "PK002", "PK003"]
    set_scope(db, other.id)
    assert [r[0] for r in run_sql(db, "SELECT sku FROM v_ai_products").rows] == ["B-001"]
    assert run_sql(db, "SELECT COUNT(*) FROM v_ai_products p JOIN v_ai_inventory i ON i.sku = p.sku").rows == [[1]]


def test_ai_logs_show_and_filter_by_branch(client, admin_h, owner_h, fake_ai, branch_id):
    b = make_branch(client, admin_h, "Cơ sở B")
    owner_b = make_user(client, admin_h, "chub", "owner", b)
    fake_ai.chat_script = ["Trả lời A", "Trả lời B"]
    client.post("/api/ai/assistant", json={"message": "Câu hỏi ở chi nhánh chính"}, headers=owner_h)
    client.post("/api/ai/assistant", json={"message": "Câu hỏi ở cơ sở B"}, headers=owner_b)
    all_logs = client.get("/api/ai/logs", headers=admin_h).json()
    assert {(i["question"], i["branch_name"]) for i in all_logs["items"]} == {
        ("Câu hỏi ở chi nhánh chính", "Chi nhánh chính"), ("Câu hỏi ở cơ sở B", "Cơ sở B")}
    assert all_logs["branch_counts"] == {str(branch_id): 1, str(b): 1}
    only_b = client.get("/api/ai/logs", params={"branch_id": b}, headers=admin_h).json()
    assert [i["question"] for i in only_b["items"]] == ["Câu hỏi ở cơ sở B"] and sum(only_b["summary"].values()) == 1
    # chủ cửa hàng chỉ thấy lượt hỏi của chi nhánh mình
    assert [i["question"] for i in client.get("/api/ai/logs", headers=owner_b).json()["items"]] == ["Câu hỏi ở cơ sở B"]


def test_full_name_cannot_be_blanked(client, admin_h):
    staff_id = user_id(client, admin_h, "staff")
    assert client.put(f"/api/users/{staff_id}", json={"full_name": "   "}, headers=admin_h).status_code == 422
