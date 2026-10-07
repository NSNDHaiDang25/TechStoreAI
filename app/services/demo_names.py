"""Tên tiếng Anh cho sản phẩm và nhóm hàng mẫu (giao diện tiếng Anh hiển thị name_en khi có).

Dùng khi nạp dữ liệu mẫu (scripts/seed.py) và khi nâng cấp CSDL cũ (database.ensure_schema điền name_en cho đúng
sản phẩm mẫu còn giữ nguyên tên gốc). Sản phẩm tên đã là tiếng Anh (Samsung Galaxy A55, iPhone 15...) không cần.
"""

# mã sản phẩm: (tên tiếng Việt gốc, tên tiếng Anh)
PRODUCT_EN = {
    "LT-ASU-01": ("Laptop Asus Vivobook 15", "Asus Vivobook 15 Laptop"),
    "LT-DEL-01": ("Laptop Dell Inspiron 14", "Dell Inspiron 14 Laptop"),
    "LT-LEN-01": ("Laptop Lenovo IdeaPad Slim 3", "Lenovo IdeaPad Slim 3 Laptop"),
    "LT-HP-01": ("Laptop HP 15s", "HP 15s Laptop"),
    "LT-ACE-01": ("Laptop Acer Aspire 5", "Acer Aspire 5 Laptop"),
    "LT-MAC-01": ("Laptop MacBook Air 13", "MacBook Air 13 Laptop"),
    "TB-SAM-01": ("Máy tính bảng Samsung Galaxy Tab A9", "Samsung Galaxy Tab A9 Tablet"),
    "TB-IPA-01": ("iPad 10.9 inch", "iPad 10.9-inch"),
    "TB-XIA-01": ("Máy tính bảng Xiaomi Pad 6", "Xiaomi Pad 6 Tablet"),
    "CH-LOG-02": ("Chuột Logitech M331", "Logitech M331 Mouse"),
    "CH-LOG-03": ("Chuột Logitech MX Master 3S", "Logitech MX Master 3S Mouse"),
    "CH-RAZ-01": ("Chuột Razer DeathAdder Essential", "Razer DeathAdder Essential Mouse"),
    "CH-FOR-01": ("Chuột không dây Forter V181", "Forter V181 Wireless Mouse"),
    "CH-DAR-01": ("Chuột Dareu EM908", "Dareu EM908 Gaming Mouse"),
    "LC-RAZ-01": ("Lót chuột Razer Gigantus", "Razer Gigantus Mouse Pad"),
    "LC-LOG-01": ("Lót chuột Logitech Desk Mat", "Logitech Desk Mat"),
    "LC-GEN-01": ("Lót chuột cỡ lớn 80x30", "Large Mouse Pad 80x30"),
    "BP-KEY-01": ("Bàn phím cơ Keychron K2", "Keychron K2 Mechanical Keyboard"),
    "BP-LOG-01": ("Bàn phím Logitech K380", "Logitech K380 Keyboard"),
    "BP-DAR-01": ("Bàn phím cơ Dareu EK87", "Dareu EK87 Mechanical Keyboard"),
    "BP-AKK-01": ("Bàn phím cơ AKKO 3068", "AKKO 3068 Mechanical Keyboard"),
    "SA-ANK-03": ("Sạc Anker 20W", "Anker 20W Charger"),
    "SA-ANK-65": ("Sạc Anker 65W", "Anker 65W Charger"),
    "SA-SAM-01": ("Sạc nhanh Samsung 25W", "Samsung 25W Fast Charger"),
    "SA-BAS-01": ("Cáp sạc USB-C Baseus 1m", "Baseus USB-C Charging Cable 1m"),
    "SA-PIN-01": ("Pin dự phòng Xiaomi 10000mAh", "Xiaomi 10000mAh Power Bank"),
    "TN-BLU-A1": ("Tai nghe Bluetooth A1", "Bluetooth Earbuds A1"),
    "TN-JBL-01": ("Tai nghe JBL Tune 510", "JBL Tune 510 Headphones"),
    "TN-SON-01": ("Tai nghe Sony WH-CH520", "Sony WH-CH520 Headphones"),
    "TN-APP-01": ("Tai nghe Apple AirPods 3", "Apple AirPods 3"),
    "TN-SAM-01": ("Tai nghe Samsung Galaxy Buds FE", "Samsung Galaxy Buds FE"),
    "TN-XIA-01": ("Tai nghe Xiaomi Redmi Buds 4", "Xiaomi Redmi Buds 4"),
    "TN-HAV-01": ("Tai nghe chụp tai Havit H2002d", "Havit H2002d Over-Ear Headset"),
    "PK-BAL-01": ("Balo laptop chống sốc 15.6 inch", "Shockproof 15.6-inch Laptop Backpack"),
    "PK-HUB-01": ("Hub USB-C 6 trong 1", "6-in-1 USB-C Hub"),
}

CATEGORY_EN = {
    "Laptop": "Laptops", "Máy tính bảng": "Tablets", "Điện thoại": "Phones", "Chuột": "Mice",
    "Lót chuột": "Mouse pads", "Bàn phím": "Keyboards", "Sạc": "Chargers", "Tai nghe": "Headphones",
    "Phụ kiện": "Accessories",
}


def _q(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def migration_sql() -> dict[tuple[str, str], list[str]]:
    """Câu UPDATE chạy một lần khi vừa thêm cột name_en: chỉ điền cho dòng còn giữ đúng tên gốc."""
    return {
        ("products", "name_en"): [f"UPDATE products SET name_en = {_q(en)} WHERE code = {_q(code)} AND name = {_q(vi)}"
                                  for code, (vi, en) in PRODUCT_EN.items()],
        ("categories", "name_en"): [f"UPDATE categories SET name_en = {_q(en)} WHERE name = {_q(vi)}"
                                    for vi, en in CATEGORY_EN.items()],
    }
