"""FR-AIA-07: gợi ý phụ kiện đi kèm ở màn hình bán hàng, dựa trên giỏ hàng hiện tại."""
import json

import pytest

from app.ai.client import AIError
from app.models import Category, Product


@pytest.fixture
def shop(db):
    laptop, mouse, pad, charger = (Category(name=n) for n in ("Laptop", "Chuột", "Lót chuột", "Sạc"))
    db.add_all([laptop, mouse, pad, charger])
    db.flush()
    items = {
        "LT1": Product(code="LT1", name="Laptop Asus Vivobook 15", category_id=laptop.id, sale_price=15_990_000, stock=5),
        "LT2": Product(code="LT2", name="Laptop Dell Inspiron 14", category_id=laptop.id, sale_price=17_490_000, stock=5),
        "CH1": Product(code="CH1", name="Chuột Logitech M331", category_id=mouse.id, sale_price=290_000, stock=20),
        "CH2": Product(code="CH2", name="Chuột Forter V181", category_id=mouse.id, sale_price=150_000, stock=30),
        "LC1": Product(code="LC1", name="Lót chuột cỡ lớn", category_id=pad.id, sale_price=120_000, stock=0),
        "SC1": Product(code="SC1", name="Sạc Anker 65W", category_id=charger.id, sale_price=890_000, stock=4),
    }
    db.add_all(items.values())
    db.commit()
    return {k: p.id for k, p in items.items()}


# FR-AIA-07 (SRS 6.3)
def test_candidates_exclude_cart_out_of_stock_and_same_main_device(client, staff_h, fake_ai, shop):
    fake_ai.response = json.dumps({"answer": "Nên mua thêm chuột", "suggestions": [
        {"code": "CH2", "reason": "Chuột không dây giá rẻ đi kèm laptop"}]})
    r = client.post("/api/ai/advisor/cross-sell", json={"product_ids": [shop["LT1"]]}, headers=staff_h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert [s["code"] for s in body["suggestions"]] == ["CH2"]
    sent = fake_ai.calls[-1]["user"]
    candidates = sent.split("DANH SÁCH ỨNG VIÊN")[1]
    assert "CH1" in candidates and "SC1" in candidates
    assert "LT2" not in candidates  # thiết bị chính cùng loại với hàng trong giỏ
    assert "LC1" not in candidates  # hết hàng (BR-41)


# FR-AIA-07 (SRS 6.3)
def test_invented_or_cart_codes_are_removed(client, staff_h, fake_ai, shop):
    fake_ai.response = json.dumps({"answer": "x", "suggestions": [
        {"code": "LT1", "reason": "đã trong giỏ"}, {"code": "ZZ999", "reason": "bịa"}, {"code": "SC1", "reason": "sạc"}]})
    body = client.post("/api/ai/advisor/cross-sell", json={"product_ids": [shop["LT1"]]}, headers=staff_h).json()
    assert [s["code"] for s in body["suggestions"]] == ["SC1"]
    assert set(body["removed"]) == {"LT1", "ZZ999"}


# FR-AIA-07 (SRS 6.3)
def test_fallback_picks_cheapest_per_accessory_group(client, staff_h, fake_ai, shop):
    fake_ai.response = AIError("Gemini quá tải (429)")
    body = client.post("/api/ai/advisor/cross-sell", json={"product_ids": [shop["LT1"]]}, headers=staff_h).json()
    assert body["source"] == "fallback"
    codes = [s["code"] for s in body["suggestions"]]
    assert codes[0] == "CH2"  # chuột rẻ nhất
    assert "SC1" in codes and "LC1" not in codes and "LT2" not in codes


# FR-AIA-07 (SRS 6.3)
def test_cross_sell_is_logged_and_forbidden_for_admin(client, staff_h, admin_h, fake_ai, shop):
    client.post("/api/ai/advisor/cross-sell", json={"product_ids": [shop["LT1"]]}, headers=staff_h)
    logs = client.get("/api/ai/logs", params={"feature": "cross_sell"}, headers=staff_h).json()
    assert logs["total"] == 1
    r = client.post("/api/ai/advisor/cross-sell", json={"product_ids": [shop["LT1"]]}, headers=admin_h)
    assert r.status_code == 403
