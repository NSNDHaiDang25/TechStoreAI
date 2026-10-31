"""Chi nhánh: quản trị viên tạo chi nhánh, gán chủ cửa hàng / nhân viên; mỗi chi nhánh độc lập, không thấy dữ liệu
của nhau; nhật ký thao tác tách theo chi nhánh."""
from app.models import BranchStock, Product
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


def product_id(client, h, code):
    return client.get("/api/products", params={"q": code}, headers=h).json()["items"][0]["id"]


def stock_of(client, h, code):
    return client.get("/api/products", params={"q": code}, headers=h).json()["items"][0]["stock"]


def set_stock(client, h, code, n):
    r = client.post(f"/api/products/{product_id(client, h, code)}/adjust-stock",
                    json={"new_stock": n, "note": "Kiểm kê"}, headers=h)
    assert r.status_code == 200, r.text


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
def test_catalog_is_shared_but_stock_sales_customers_are_per_branch(client, admin_h, owner_h, staff_h, db):
    b = make_branch(client, admin_h, "Cơ sở B")
    owner_b = make_user(client, admin_h, "chub", "owner", b)
    staff_b = make_user(client, admin_h, "nvb", "staff", b)

    # Cùng danh mục sản phẩm (tên, giá), tồn kho riêng: cơ sở B mới mở chưa có hàng
    items_b = {p["code"]: p for p in client.get("/api/products", headers=owner_b).json()["items"]}
    assert set(items_b) == {"PK001", "PK002", "PK003"}
    assert items_b["PK001"]["sale_price"] == 350_000 and items_b["PK001"]["stock"] == 0
    assert stock_of(client, owner_h, "PK001") == 12

    # Chỉ chi nhánh chính sửa danh mục; giá đổi ở chi nhánh chính thì chi nhánh khác thấy ngay
    assert new_product(client, owner_b, "B-001").status_code == 403
    pk001 = product_id(client, owner_h, "PK001")
    assert client.put(f"/api/products/{pk001}", json={"sale_price": 1}, headers=owner_b).status_code == 403
    change_price(client, owner_h, "PK001", 360_000)
    assert client.get(f"/api/products/{pk001}", headers=owner_b).json()["sale_price"] == 360_000
    assert new_product(client, owner_h, "PK009", stock=4).status_code == 201
    assert stock_of(client, owner_b, "PK009") == 0 and stock_of(client, owner_h, "PK009") == 4

    # Kiểm kê, bán hàng ở cơ sở B chỉ đổi tồn của cơ sở B
    set_stock(client, owner_b, "PK003", 5)
    inv = client.post("/api/invoices", json={"items": [{"product_id": product_id(client, staff_b, "PK003"), "quantity": 1}]},
                      headers=staff_b)
    assert inv.status_code == 201, inv.text
    assert stock_of(client, owner_b, "PK003") == 4 and stock_of(client, owner_h, "PK003") == 50
    r = client.post("/api/invoices", json={"items": [{"product_id": pk001, "quantity": 1}]}, headers=staff_b)
    assert r.status_code == 409  # chi nhánh chính còn 12 nhưng cơ sở B hết hàng
    stocks = {s.branch_id: s.stock for s in db.query(BranchStock).execution_options(all_branches=True)
              .filter_by(product_id=product_id(client, owner_h, "PK003"))}
    assert stocks[b] == 4

    # Khách hàng, hóa đơn vẫn riêng từng chi nhánh
    r = client.post("/api/customers", json={"name": "Khách B", "phone": "0909000111"}, headers=staff_b)
    assert r.status_code == 201, r.text
    assert "Khách B" not in {c["name"] for c in client.get("/api/customers", headers=staff_h).json()["items"]}
    assert [i["code"] for i in client.get("/api/invoices", headers=owner_h).json()["items"]] == []
    assert len(client.get("/api/invoices", headers=owner_b).json()["items"]) == 1
    assert client.get(f"/api/invoices/{inv.json()['id']}", headers=owner_h).status_code == 404


def test_invoice_codes_stay_unique_across_branches(client, admin_h, owner_h):
    b = make_branch(client, admin_h, "Cơ sở B")
    owner_b = make_user(client, admin_h, "chub", "owner", b)
    set_stock(client, owner_b, "PK003", 5)
    pa = product_id(client, owner_h, "PK001")
    pb = product_id(client, owner_b, "PK003")
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
    assert stock_of(client, staff_h, "PK001") == 12
    assert client.get("/api/customers", headers=staff_h).json()["total"] == 1
    assert client.put(f"/api/users/{staff_id}", json={"branch_id": b}, headers=admin_h).status_code == 200
    assert stock_of(client, staff_h, "PK001") == 0  # giờ làm việc ở cơ sở B: kho của cơ sở B
    assert client.get("/api/customers", headers=staff_h).json()["total"] == 0


def test_inactive_branch_cannot_sign_in(client, admin_h, branch_id):
    b = make_branch(client, admin_h, "Cơ sở B")
    make_user(client, admin_h, "nvb", "staff", b)
    client.put(f"/api/branches/{b}", json={"name": "Cơ sở B", "is_active": False}, headers=admin_h)
    r = client.post("/api/auth/login", json={"username": "nvb", "password": "Matkhau123"})
    assert r.status_code == 403 and "ngừng hoạt động" in r.json()["detail"]
    # Chi nhánh chính không được ngừng hoạt động (nơi tổng hợp số liệu)
    r = client.put(f"/api/branches/{branch_id}", json={"name": "Chi nhánh chính", "is_active": False}, headers=admin_h)
    assert r.status_code == 400


# ---------------- Chi nhánh chính tổng hợp số liệu mọi chi nhánh ----------------
def _sell(client, h, code, qty=1):
    pid = product_id(client, h, code)
    r = client.post("/api/invoices", json={"items": [{"product_id": pid, "quantity": qty}], "payment_method": "cash"},
                    headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def test_main_branch_sees_invoices_and_revenue_of_all_branches(client, admin_h, owner_h, staff_h, branch_id):
    b = make_branch(client, admin_h, "Cơ sở B")
    owner_b = make_user(client, admin_h, "chub", "owner", b)
    set_stock(client, owner_b, "PK003", 5)
    inv_b = _sell(client, owner_b, "PK003", 2)
    inv_main = _sell(client, owner_h, "PK001")

    me = client.get("/api/auth/me", headers=owner_h).json()
    assert me["branch_is_main"] is True
    assert client.get("/api/auth/me", headers=owner_b).json()["branch_is_main"] is False

    # Mặc định vẫn chỉ chi nhánh của mình
    assert [i["code"] for i in client.get("/api/invoices", headers=owner_h).json()["items"]] == [inv_main["code"]]
    # Tất cả chi nhánh
    all_inv = client.get("/api/invoices", params={"branch": "all"}, headers=owner_h).json()
    assert {i["code"] for i in all_inv["items"]} == {inv_main["code"], inv_b["code"]}
    assert all_inv["sum_paid"] == inv_main["total"] + inv_b["total"]
    assert {i["branch_name"] for i in all_inv["items"]} == {"Chi nhánh chính", "Cơ sở B"}
    # Một chi nhánh cụ thể, mở chi tiết hóa đơn chi nhánh khác
    only_b = client.get("/api/invoices", params={"branch": b}, headers=owner_h).json()
    assert [i["code"] for i in only_b["items"]] == [inv_b["code"]]
    detail = client.get(f"/api/invoices/{inv_b['id']}", params={"branch": "all"}, headers=owner_h)
    assert detail.status_code == 200 and detail.json()["branch_name"] == "Cơ sở B"

    # Doanh thu tổng và theo chi nhánh
    rev = client.get("/api/reports/revenue", params={"branch": "all"}, headers=owner_h).json()
    assert rev["summary"]["revenue"] == inv_main["total"] + inv_b["total"]
    by_branch = {r["branch_name"]: r["revenue"] for r in rev["by_branch"]}
    assert by_branch == {"Chi nhánh chính": inv_main["total"], "Cơ sở B": inv_b["total"]}
    assert client.get("/api/reports/revenue", headers=owner_h).json()["by_branch"] == []
    dash = client.get("/api/reports/dashboard", params={"branch": "all"}, headers=owner_h).json()
    assert dash["today"]["revenue"] == inv_main["total"] + inv_b["total"]
    assert len(dash["by_branch_month"]) == 2
    # Việc cần xử lý chỉ tính chi nhánh mình (hóa đơn chi nhánh khác không xử lý được)
    _sell_pending = client.post("/api/invoices", json={"items": [{"product_id": product_id(client, owner_b, "PK003"),
                                "quantity": 1}], "payment_method": "bank_transfer"}, headers=owner_b)
    assert _sell_pending.status_code == 201, _sell_pending.text
    dash = client.get("/api/reports/dashboard", params={"branch": "all"}, headers=owner_h).json()
    assert dash["pending_payment"] == 0
    assert client.get("/api/reports/dashboard", headers=owner_b).json()["pending_payment"] == 1
    r = client.get("/api/reports/export/revenue", params={"branch": "all", "format": "xlsx"}, headers=owner_h)
    assert r.status_code == 200
    r = client.get("/api/reports/export/invoices", params={"branch": "all", "format": "csv"}, headers=owner_h)
    assert r.status_code == 200 and "Chi nhánh" in r.content.decode("utf-8-sig") and inv_b["code"] in r.content.decode("utf-8-sig")

    # Chỉ xem: không thao tác được trên hóa đơn chi nhánh khác
    r = client.post(f"/api/invoices/{inv_b['id']}/cancel", params={"branch": "all"}, json={"reason": "Lập sai hóa đơn cần hủy"},
                    headers=owner_h)
    assert r.status_code == 404

    # Chi nhánh thường, nhân viên chi nhánh chính: không được xem chi nhánh khác
    assert client.get("/api/invoices", params={"branch": "all"}, headers=owner_b).status_code == 403
    assert client.get("/api/reports/revenue", params={"branch": branch_id}, headers=owner_b).status_code == 403
    assert client.get("/api/invoices", params={"branch": "all"}, headers=staff_h).status_code == 403
    assert client.get("/api/branches/options", headers=owner_b).status_code == 403
    assert client.get("/api/invoices", params={"branch": "999"}, headers=owner_h).status_code == 404
    opts = client.get("/api/branches/options", headers=owner_h).json()
    assert [o["name"] for o in opts] == ["Chi nhánh chính", "Cơ sở B"] and opts[0]["is_main"]


def test_admin_moves_main_branch(client, admin_h, owner_h, branch_id):
    b = make_branch(client, admin_h, "Cơ sở B")
    owner_b = make_user(client, admin_h, "chub", "owner", b)
    # Phải luôn có một chi nhánh chính
    r = client.put(f"/api/branches/{branch_id}", json={"name": "Chi nhánh chính", "is_main": False}, headers=admin_h)
    assert r.status_code == 400
    r = client.put(f"/api/branches/{b}", json={"name": "Cơ sở B", "is_main": True}, headers=admin_h)
    assert r.status_code == 200 and r.json()["is_main"] is True
    mains = [x["name"] for x in client.get("/api/branches", headers=admin_h).json() if x["is_main"]]
    assert mains == ["Cơ sở B"]
    assert client.get("/api/invoices", params={"branch": "all"}, headers=owner_b).status_code == 200
    assert client.get("/api/invoices", params={"branch": "all"}, headers=owner_h).status_code == 403


# ---------------- Nhật ký thao tác theo chi nhánh ----------------
def test_actions_are_logged_under_the_branch_of_the_user(client, admin_h, owner_h, branch_id):
    b = make_branch(client, admin_h, "Cơ sở B")
    owner_b = make_user(client, admin_h, "chub", "owner", b)
    set_stock(client, owner_h, "PK001", 10)
    set_stock(client, owner_b, "PK001", 7)

    in_main = logs(client, admin_h, branch_id=branch_id, action="STOCK_ADJUST")["items"]
    in_b = logs(client, admin_h, branch_id=b, action="STOCK_ADJUST")["items"]
    assert [i["branch_name"] for i in in_main] == ["Chi nhánh chính"]
    assert [i["branch_name"] for i in in_b] == ["Cơ sở B"] and "7" in in_b[0]["new_value"]
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
    """Hỏi đáp dữ liệu (SQL do AI viết chạy trên view v_ai_*): cùng danh mục, tồn kho của chi nhánh người hỏi."""
    from app.ai.text_to_sql import run_sql
    from app.models import Branch
    from app.services.branch_scope import set_scope
    other = Branch(name="Cơ sở B")
    db.add(other)
    db.flush()
    pk003 = db.query(Product).filter_by(code="PK003").one()
    db.add(BranchStock(product_id=pk003.id, branch_id=other.id, stock=7))
    db.commit()
    sql = "SELECT sku, stock_qty FROM v_ai_inventory ORDER BY sku"
    assert run_sql(db, sql).rows == [["PK001", 12], ["PK002", 0], ["PK003", 50]]
    set_scope(db, other.id)
    assert run_sql(db, sql).rows == [["PK001", 0], ["PK002", 0], ["PK003", 7]]
    assert run_sql(db, "SELECT COUNT(*) FROM v_ai_products p JOIN v_ai_inventory i ON i.sku = p.sku").rows == [[3]]


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


def test_suppliers_are_shared_and_managed_by_main_branch(client, admin_h, owner_h):
    b = make_branch(client, admin_h, "Cơ sở B")
    owner_b = make_user(client, admin_h, "chub", "owner", b)
    r = client.post("/api/suppliers", json={"name": "NCC Chung", "phone": "0911222333"}, headers=owner_h)
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    # Chi nhánh khác thấy và dùng được nhà cung cấp, nhưng không thêm / sửa / xóa
    assert "NCC Chung" in {s["name"] for s in client.get("/api/suppliers", headers=owner_b).json()}
    assert client.post("/api/suppliers", json={"name": "NCC B"}, headers=owner_b).status_code == 403
    assert client.put(f"/api/suppliers/{sid}", json={"name": "Đổi tên"}, headers=owner_b).status_code == 403
    assert client.delete(f"/api/suppliers/{sid}", headers=owner_b).status_code == 403
    r = client.post("/api/purchase-orders", json={"supplier_id": sid, "confirm": True, "items": [
        {"product_id": product_id(client, owner_b, "PK003"), "quantity": 3, "unit_cost": 90_000}]}, headers=owner_b)
    assert r.status_code == 201, r.text
    assert stock_of(client, owner_b, "PK003") == 3
    # Số phiếu nhập là của từng chi nhánh
    stats = {s["name"]: s["order_count"] for s in client.get("/api/suppliers", headers=owner_b).json()}
    assert stats["NCC Chung"] == 1
    assert {s["name"]: s["order_count"] for s in client.get("/api/suppliers", headers=owner_h).json()}["NCC Chung"] == 0
    # Đã có phiếu nhập ở chi nhánh B: chi nhánh chính xóa thì chỉ chuyển sang ngừng hợp tác
    r = client.delete(f"/api/suppliers/{sid}", headers=owner_h)
    assert r.status_code == 200 and "ngừng hợp tác" in r.json()["message"]


def test_low_stock_is_checked_per_branch_in_all_branch_view(client, admin_h, owner_h):
    b = make_branch(client, admin_h, "Cơ sở B")
    owner_b = make_user(client, admin_h, "chub", "owner", b)
    set_stock(client, owner_b, "PK003", 100)
    # Chi nhánh chính: PK001 còn 12, PK002 hết, PK003 còn 50 (mức tối thiểu mặc định 5)
    own = {p["code"] for p in client.get("/api/reports/low-stock", headers=owner_h).json()}
    assert own == {"PK002"}
    rows = client.get("/api/reports/low-stock", params={"branch": "all"}, headers=owner_h).json()
    pairs = {(p["code"], p["branch_name"]) for p in rows}
    # Tổng PK001 = 12 vẫn trên mức tối thiểu, nhưng cơ sở B hết hàng: phải cảnh báo riêng cơ sở B
    assert pairs == {("PK002", "Chi nhánh chính"), ("PK001", "Cơ sở B"), ("PK002", "Cơ sở B")}
    dash = client.get("/api/reports/dashboard", params={"branch": "all"}, headers=owner_h).json()
    assert len(dash["low_stock"]) == 3 and all(p["image_url"] is None or p["image_url"] for p in dash["low_stock"])


def test_main_branch_sees_purchases_of_other_branches_with_branch_and_person(client, admin_h, owner_h):
    b = make_branch(client, admin_h, "Cơ sở B")
    owner_b = make_user(client, admin_h, "chub", "owner", b)
    staff_b = make_user(client, admin_h, "nvb", "staff", b)
    sid = client.post("/api/suppliers", json={"name": "NCC Chung"}, headers=owner_h).json()["id"]
    # Nhân viên cơ sở B lập nháp, chủ cơ sở B xác nhận nhập kho
    r = client.post("/api/purchase-orders", json={"supplier_id": sid, "items": [
        {"product_id": product_id(client, staff_b, "PK003"), "quantity": 4}]}, headers=staff_b)
    assert r.status_code == 201, r.text
    po_id = r.json()["id"]
    client.put(f"/api/purchase-orders/{po_id}", json={"supplier_id": sid, "items": [
        {"product_id": product_id(client, owner_b, "PK003"), "quantity": 4, "unit_cost": 90_000}]}, headers=owner_b)
    assert client.post(f"/api/purchase-orders/{po_id}/confirm", headers=owner_b).status_code == 200

    # Mặc định chi nhánh chính chỉ thấy phiếu của mình; xem tất cả thì thấy phiếu cơ sở B kèm chi nhánh, người lập,
    # người xác nhận nhập kho
    assert client.get("/api/purchase-orders", headers=owner_h).json()["total"] == 0
    rows = client.get("/api/purchase-orders", params={"branch": "all"}, headers=owner_h).json()["items"]
    assert [(o["branch_name"], o["user_name"], o["confirmed_by_name"]) for o in rows] == [("Cơ sở B", "NVB", "CHUB")]
    detail = client.get(f"/api/purchase-orders/{po_id}", params={"branch": "all"}, headers=owner_h)
    assert detail.status_code == 200 and detail.json()["items"][0]["quantity"] == 4
    # Chỉ xem: không hủy được phiếu chi nhánh khác
    r = client.post(f"/api/purchase-orders/{po_id}/cancel", params={"branch": "all"}, json={"reason": "Nhập sai số lượng"},
                    headers=owner_h)
    assert r.status_code == 404
    # Chuông thông báo của chi nhánh chính báo chi nhánh khác vừa nhập hàng
    notes = {i["type"]: i for i in client.get("/api/notifications", headers=owner_h).json()["items"]}
    assert notes["branch_imports"]["count"] == 1 and "Cơ sở B" in notes["branch_imports"]["names"][0]
    assert "branch_imports" not in {i["type"] for i in client.get("/api/notifications", headers=owner_b).json()["items"]}
    # Chi nhánh thường không xem được phiếu chi nhánh khác
    assert client.get("/api/purchase-orders", params={"branch": "all"}, headers=owner_b).status_code == 403


def test_dashboard_numbers_match_the_linked_invoice_list(client, admin_h, owner_h):
    """Số hóa đơn, doanh thu ở Tổng quan khớp với trang Hóa đơn mở từ liên kết (status=revenue, cùng ngày, cùng chi nhánh)."""
    b = make_branch(client, admin_h, "Cơ sở B")
    owner_b = make_user(client, admin_h, "chub", "owner", b)
    set_stock(client, owner_b, "PK003", 5)
    _sell(client, owner_b, "PK003", 2)
    sold = _sell(client, owner_h, "PK001", 2)
    _sell(client, owner_h, "PK001")
    # Không tính doanh thu: chờ chuyển khoản
    r = client.post("/api/invoices", json={"items": [{"product_id": product_id(client, owner_h, "PK001"), "quantity": 1}],
                                           "payment_method": "bank_transfer"}, headers=owner_h)
    assert r.status_code == 201, r.text
    # Trả 1 món: Tổng quan trừ tiền hoàn
    item = client.get(f"/api/invoices/{sold['id']}", headers=owner_h).json()["items"][0]
    r = client.post("/api/returns", json={"invoice_id": sold["id"], "reason": "Khách đổi ý không dùng",
                                          "items": [{"invoice_item_id": item["id"], "quantity": 1}]}, headers=owner_h)
    assert r.status_code == 201, r.text

    dash = client.get("/api/reports/dashboard", params={"branch": "all"}, headers=owner_h).json()
    day = {"status": "revenue", "date_from": dash["date"], "date_to": dash["date"]}
    inv = client.get("/api/invoices", params={**day, "branch": "all"}, headers=owner_h).json()
    assert inv["total"] == dash["today"]["invoice_count"] == 3
    assert inv["sum_paid"] - inv["refunds"] == dash["today"]["revenue"]
    for row in dash["by_branch_month"]:
        one = client.get("/api/invoices", params={**day, "date_from": dash["date"][:8] + "01", "branch": row["branch_id"]},
                         headers=owner_h).json()
        assert one["total"] == row["invoice_count"]
        assert one["sum_paid"] - one["refunds"] == row["revenue"]
    # Danh sách thường (mọi trạng thái) vẫn có hóa đơn chờ chuyển khoản
    assert client.get("/api/invoices", params={"branch": "all"}, headers=owner_h).json()["total"] == 4
