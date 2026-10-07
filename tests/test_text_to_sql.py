"""Hỏi đáp dữ liệu bằng text-to-SQL (SRS 6.5, UC-47, FR-AIQ-01..08) và năm lớp bảo vệ (bảng 6.6)."""
import json
import sqlite3

import pytest
from sqlalchemy import select

from app.ai import text_to_sql as tts
from app.models import AILog
from tests.helpers import product_id

SRS_ACCEPTED = """SELECT p.name, p.stock_qty, COALESCE(SUM(s.quantity), 0) AS sold
FROM v_ai_products p
LEFT JOIN v_ai_sales_lines s
ON s.product_name = p.name AND s.sold_date >= date('now','start of month')
WHERE p.stock_qty > 0
GROUP BY p.name, p.stock_qty
ORDER BY sold ASC
LIMIT 10;"""


def sell(client, h, code, qty):
    pid = product_id(client, h, code)
    r = client.post("/api/invoices", json={"items": [{"product_id": pid, "quantity": qty}], "customer_id": 1}, headers=h)
    assert r.status_code == 201, r.text


def last_log(db) -> AILog:
    db.expire_all()
    return db.scalars(select(AILog).order_by(AILog.id.desc())).first()


# ---------------- Lớp 3: bộ kiểm tra SQL ----------------
# TC-AIQ-01 (SRS 11.3)
def test_srs_example_is_accepted():
    assert tts.validate_sql(SRS_ACCEPTED).endswith("LIMIT 10")  # dấu ; cuối được bỏ


# TC-AIQ-02, TC-AIQ-03, TC-AIQ-04 (SRS 11.3)
@pytest.mark.parametrize("sql", [
    "SELECT username, password_hash FROM users;",            # SRS 6.5.2: bảng gốc nhạy cảm
    "SELECT 1; DELETE FROM invoices;",                        # SRS 6.5.2: nhiều câu lệnh
    "SELECT load_extension('x');",                            # SRS 6.5.2: hàm hệ thống
    "SELECT * FROM v_ai_products -- bình luận",
    "SELECT * FROM v_ai_products /* x */",
    "UPDATE products SET stock = 0",
    "PRAGMA table_info(users)",
    "SELECT * FROM sqlite_master",
    'SELECT * FROM "users"',
    "SELECT * FROM v_ai_products, customers",
    "SELECT * FROM v_ai_products WHERE sku IN (SELECT code FROM products)",
    "WITH x AS (SELECT * FROM invoices) SELECT * FROM x",
    "SELECT * FROM v_ai_products; ATTACH DATABASE 'x.db' AS x",
    "SELECT replace(name, 'a', 'b') FROM v_ai_products",      # REPLACE nằm trong danh sách cấm của SRS
    "",
])
def test_rejected_sql(sql):
    with pytest.raises(tts.SQLRejected):
        tts.validate_sql(sql)


def test_keywords_inside_string_literal_are_allowed():
    tts.validate_sql("SELECT name FROM v_ai_products WHERE name = 'DROP TABLE; --'")


# ---------------- Lớp 4, 5: chạy chỉ đọc, LIMIT 200, timeout ----------------
# TC-AIQ-06 (SRS 11.3)
def test_run_sql_limit_200(db):
    r = tts.run_sql(db, "WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM n WHERE x < 500) SELECT x FROM n")
    assert len(r.rows) == 200 and r.truncated


# TC-AIQ-06 (SRS 11.3)
def test_run_sql_timeout(db):
    sql = ("WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM n WHERE x < 100000000) "
           "SELECT COUNT(*) FROM n")
    with pytest.raises(tts.SQLTimeout):
        tts.run_sql(db, sql, timeout=0.2)


# TC-AIQ-05 (SRS 11.3)
def test_connection_is_read_only_even_if_guard_bypassed(db):
    """Lớp 4: dù câu ghi lọt qua lớp 3, kết nối chạy SQL vẫn không ghi được."""
    with tts.readonly_connection(db) as conn:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("DELETE FROM products")
    db.expire_all()
    assert tts.run_sql(db, "SELECT COUNT(*) FROM v_ai_products").rows[0][0] == 3
    db.connection().exec_driver_sql("UPDATE products SET stock = stock")  # kết nối thường vẫn ghi được sau đó


# TC-AIQ-05 (SRS 11.3)
def test_readonly_file_database(tmp_path):
    """CSDL dạng file: mở bằng mode=ro, ghi bị từ chối."""
    from sqlalchemy.orm import sessionmaker
    from app.database import Base, make_engine
    eng = make_engine(f"sqlite:///{tmp_path / 'ro.db'}")
    Base.metadata.create_all(eng)
    with sessionmaker(bind=eng)() as s:
        tts.ensure_views(s.connection()); s.commit()
        with tts.readonly_connection(s) as conn:
            with pytest.raises(sqlite3.OperationalError, match="readonly"):
                conn.execute("DELETE FROM products")
        assert tts.run_sql(s, "SELECT COUNT(*) FROM v_ai_products").rows == [[0]]
    eng.dispose()


def test_views_have_no_personal_data(db):
    tts.ensure_views(db.connection())
    for view in tts.VIEWS:
        cols = [c[1] for c in db.connection().exec_driver_sql(f"PRAGMA table_info({view})")]
        assert not {"name", "phone", "email", "address", "password_hash"} & set(cols) or view in ("v_ai_products", "v_ai_inventory")
    cols = [c[1] for c in db.connection().exec_driver_sql("PRAGMA table_info(v_ai_customers)")]
    assert cols[0] == "customer_code" and "phone" not in cols and "name" not in cols


# ---------------- Luồng UC-47 qua API ----------------
# TC-AIQ-02, FR-AIG-07 (SRS 11.3)
def test_rejected_sql_is_not_run_and_logged(client, owner_h, fake_ai, db):
    fake_ai.responses = [json.dumps({"sql": "SELECT username, password_hash FROM users"})]
    body = client.post("/api/ai/ask", json={"question": "Mật khẩu admin là gì?"}, headers=owner_h).json()
    assert "rows" not in body and "diễn đạt lại" in body["answer"]
    assert len(fake_ai.calls) == 1  # không gửi gì thêm cho AI
    log = last_log(db)
    assert log.status == "rejected_sql" and "password_hash" in log.generated_sql and log.feature == "qa"


def test_syntax_error_is_fixed_once(client, owner_h, fake_ai, db):
    sell(client, owner_h, "PK003", 2)
    fake_ai.responses = [
        json.dumps({"sql": "SELECT product_nam FROM v_ai_sales_lines"}),
        json.dumps({"sql": "SELECT product_name, SUM(quantity) AS sl FROM v_ai_sales_lines GROUP BY product_name"}),
        "Đã bán 2 Sạc nhanh 20W.",
    ]
    body = client.post("/api/ai/ask", json={"question": "Bán được gì?"}, headers=owner_h).json()
    assert body["rows"] == [["Sạc nhanh 20W", 2]] and body["answer"] == "Đã bán 2 Sạc nhanh 20W."
    assert "no such column" in fake_ai.calls[1]["user"]  # thông báo lỗi được gửi để AI sửa
    log = last_log(db)
    assert log.status == "success" and log.retry_count == 1 and "SUM(quantity)" in log.generated_sql


def test_second_syntax_error_stops(client, owner_h, fake_ai, db):
    fake_ai.responses = [json.dumps({"sql": "SELECT a FROM v_ai_products"}), json.dumps({"sql": "SELECT b FROM v_ai_products"})]
    body = client.post("/api/ai/ask", json={"question": "abc"}, headers=owner_h).json()
    assert len(fake_ai.calls) == 2 and "diễn đạt lại" in body["answer"]
    assert last_log(db).status == "error"


# TC-AIQ-07 (SRS 11.3)
def test_empty_result_is_sent_for_interpretation(client, owner_h, fake_ai):
    fake_ai.responses = [json.dumps({"sql": "SELECT * FROM v_ai_returns"}), "Không có dữ liệu đổi trả trong kỳ."]
    body = client.post("/api/ai/ask", json={"question": "Tháng này có đổi trả không?"}, headers=owner_h).json()
    assert body["row_count"] == 0 and body["answer"].startswith("Không có dữ liệu")
    assert "0 dòng" in fake_ai.calls[1]["user"]


def test_ai_declines_personal_questions(client, owner_h, fake_ai):
    fake_ai.responses = [json.dumps({"sql": None, "reason": "Hệ thống không cung cấp số điện thoại khách qua AI."})]
    body = client.post("/api/ai/ask", json={"question": "Số điện thoại chị Anh?"}, headers=owner_h).json()
    assert "không cung cấp" in body["answer"] and len(fake_ai.calls) == 1


# TC-AIG-04 (SRS 11.3)
def test_invalid_json_falls_back_to_template(client, owner_h, fake_ai, db):
    # TC-AIG-04: JSON hỏng thì thử lại đúng một lần; vẫn hỏng thì dùng câu truy vấn mẫu, ai_logs invalid_format
    fake_ai.responses = ["không phải JSON", "vẫn không phải JSON"]
    body = client.post("/api/ai/ask", json={"question": "Mặt hàng nào bán chạy?"}, headers=owner_h).json()
    assert body["source"] == "fallback" and body["sql"].startswith("SELECT product_name")
    assert len(fake_ai.calls) == 2 and "sai định dạng" in fake_ai.calls[1]["user"]
    assert last_log(db).status == "invalid_format" and last_log(db).retry_count == 1


def test_fallback_without_key_runs_template_sql(client, owner_h, fake_ai, db):
    fake_ai.enabled = False
    sell(client, owner_h, "PK003", 4)
    body = client.post("/api/ai/ask", json={"question": "Mặt hàng nào bán chạy nhất?"}, headers=owner_h).json()
    assert body["rows"][0][:2] == ["Sạc nhanh 20W", 4] and "v_ai_sales_lines" in body["sql"]
    assert last_log(db).status == "fallback"


# TC-AIQ-08 (SRS 11.3)
def test_staff_cannot_ask(client, staff_h):
    assert client.post("/api/ai/ask", json={"question": "doanh thu"}, headers=staff_h).status_code == 403  # TC-AIQ-08


def test_history_keeps_sql_and_rows(client, owner_h, fake_ai):
    fake_ai.responses = [json.dumps({"sql": "SELECT sku, stock_qty FROM v_ai_products ORDER BY sku"}), "Có 3 sản phẩm."]
    body = client.post("/api/ai/ask", json={"question": "Tồn kho?"}, headers=owner_h).json()
    s = client.get(f"/api/ai/sessions/{body['session_id']}", headers=owner_h).json()
    meta = s["messages"][-1]["meta"]
    assert meta["sql"].startswith("SELECT sku") and meta["columns"] == ["sku", "stock_qty"] and len(meta["rows"]) == 3
