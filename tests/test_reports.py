"""Test báo cáo doanh thu, thống kê và xuất file."""
from datetime import date

from tests.helpers import product_id


def sell(client, h, items, **extra):
    r = client.post("/api/invoices", json={"items": items, **extra}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


# TC-RPT-01 (SRS 11.3)
def test_revenue_excludes_cancelled_invoices(client, owner_h):
    pk1, pk3 = product_id(client, owner_h, "PK001"), product_id(client, owner_h, "PK003")
    sell(client, owner_h, [{"product_id": pk1, "quantity": 2}], discount=50_000)  # 650.000
    sell(client, owner_h, [{"product_id": pk3, "quantity": 3}])                   # 570.000
    c = sell(client, owner_h, [{"product_id": pk1, "quantity": 1}])
    client.post(f"/api/invoices/{c['id']}/cancel", json={"reason": "Lập sai hóa đơn"}, headers=owner_h)

    today = date.today().isoformat()
    data = client.get("/api/reports/revenue", params={"date_from": today, "date_to": today}, headers=owner_h).json()
    s = data["summary"]
    assert s["invoice_count"] == 2
    assert s["revenue"] == 1_220_000
    assert s["discount"] == 50_000
    assert s["cost"] == 2 * 220_000 + 3 * 95_000
    # FR-RPT-05: lãi gộp = doanh thu chưa VAT - giá vốn. VAT 10% đã gồm trong giá: 59.091 + 51.818
    assert s["vat"] == 59_091 + 51_818 and s["revenue_net"] == 1_220_000 - 110_909
    assert s["gross_profit"] == 1_220_000 - 110_909 - 725_000
    assert data["by_day"] == [{"date": today, "revenue": 1_220_000, "invoice_count": 2}]


# TC-RPT-03, FR-RPT-03 (SRS 11.3)
def test_top_and_slow_products(client, owner_h):
    pk1, pk3 = product_id(client, owner_h, "PK001"), product_id(client, owner_h, "PK003")
    sell(client, owner_h, [{"product_id": pk3, "quantity": 5}])
    sell(client, owner_h, [{"product_id": pk1, "quantity": 1}])
    data = client.get("/api/reports/revenue", headers=owner_h).json()
    assert [p["code"] for p in data["top_products"]] == ["PK003", "PK001"]
    # PK002 hết hàng nên không nằm trong danh sách bán chậm; PK001 bán ít hơn PK003
    assert [p["code"] for p in data["slow_products"]] == ["PK001", "PK003"]
    assert all("image_url" in p for p in data["top_products"] + data["slow_products"])  # bảng giao diện có ảnh
    assert data["by_category"][0]["category"] == "Phụ kiện"


def test_monthly_report_has_12_months(client, owner_h):
    pk1 = product_id(client, owner_h, "PK001")
    sell(client, owner_h, [{"product_id": pk1, "quantity": 1}])
    months = client.get("/api/reports/monthly", headers=owner_h).json()
    assert len(months) == 12
    assert months[date.today().month - 1]["revenue"] == 350_000


# FR-RPT-01
def test_dashboard_lists_low_stock(client, owner_h):
    d = client.get("/api/reports/dashboard", headers=owner_h).json()
    assert "PK002" in [p["code"] for p in d["low_stock"]]


def test_staff_cannot_view_reports(client, staff_h):
    assert client.get("/api/reports/revenue", headers=staff_h).status_code == 403
    assert client.post("/api/ai/report", json={}, headers=staff_h).status_code == 403
    assert client.post("/api/ai/ask", json={"question": "doanh thu?"}, headers=staff_h).status_code == 403


def test_invalid_date_returns_400(client, owner_h):
    r = client.get("/api/reports/revenue", params={"date_from": "31/12/2025"}, headers=owner_h)
    assert r.status_code == 400


# TC-EXP-01, TC-EXP-02 (SRS 11.3)
def test_export_formats(client, owner_h):
    pk1 = product_id(client, owner_h, "PK001")
    sell(client, owner_h, [{"product_id": pk1, "quantity": 1}])
    csv = client.get("/api/reports/export/invoices", params={"format": "csv"}, headers=owner_h)
    assert csv.status_code == 200
    lines = csv.content.decode("utf-8-sig").strip().splitlines()
    assert lines[0].startswith("Mã HĐ") and len(lines) == 2
    xlsx = client.get("/api/reports/export/revenue", params={"format": "xlsx"}, headers=owner_h)
    assert xlsx.content[:2] == b"PK"  # file zip
    pdf = client.get("/api/reports/export/revenue", params={"format": "pdf"}, headers=owner_h)
    assert pdf.content[:4] == b"%PDF"
