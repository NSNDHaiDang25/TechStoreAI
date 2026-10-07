"""Nạp dữ liệu mẫu theo SRS Phụ lục A (FR-SYS-01): 3 tài khoản, 8 nhóm hàng, 40 sản phẩm, 20 khách hàng,
5 nhà cung cấp, 3 khuyến mãi, 60 hóa đơn rải trong 60 ngày (hạt giống cố định 2026).

Mọi dữ liệu đi qua đúng service nghiệp vụ (phiếu nhập, bán hàng) nên tồn kho, serial, điểm, bảo hành luôn khớp.
Tồn kho sau khi nạp bằng đúng cột "Tồn" của bảng A.3: phiếu nhập đầu kỳ = tồn mong muốn + số sẽ bán trong lịch sử.

Chạy:  python -m scripts.seed          (xóa và tạo lại toàn bộ dữ liệu)
Mật khẩu ban đầu lấy từ biến môi trường SEED_ADMIN_PASSWORD, SEED_OWNER_PASSWORD, SEED_STAFF_PASSWORD.
"""
import calendar
import os
import random
import sys
from collections import defaultdict
from datetime import datetime, time, timedelta
from pathlib import Path

from app.database import Base, SessionLocal, engine, ensure_schema
from app.models import Category, Customer, FaceProfile, Product, Promotion, Supplier, User, now
from app.schemas import InvoiceIn, InvoiceItemIn, PurchaseItemIn, PurchaseOrderIn
from app.security import hash_password
from app.services import face, loyalty, purchasing, sales
from app.services.demo_names import CATEGORY_EN, PRODUCT_EN

SEED = 2026
HISTORY_DAYS = 60
HISTORY_INVOICES = 60
FACE_SAMPLES = Path(__file__).resolve().parent / "face_samples"  # ảnh mẫu Face ID theo tên đăng nhập

# Bảng A.1: tên đăng nhập, họ tên, vai trò, biến môi trường mật khẩu, mật khẩu mặc định, bắt đổi mật khẩu
USERS = [
    ("admin", "Quản trị hệ thống", "admin", "SEED_ADMIN_PASSWORD", "admin123", True),
    ("chucuahang", "Nguyễn Tất Phi", "owner", "SEED_OWNER_PASSWORD", "owner123", False),
    ("nhanvien01", "Nguyễn Phạm Phương Lan", "staff", "SEED_STAFF_PASSWORD", "staff123", False),
]

# Bảng A.2: nhóm hàng, theo serial
CATEGORIES = [("Laptop", True), ("Máy tính bảng", True), ("Điện thoại", True), ("Chuột", False),
              ("Lót chuột", False), ("Bàn phím", False), ("Sạc", False), ("Tai nghe", False)]

# Bảng A.3: SKU, tên, nhóm, giá bán, giá nhập, tồn, hãng, mô tả ngắn
PRODUCTS = [
    ("LT-ASU-01", "Laptop Asus Vivobook 15", "Laptop", 15_990_000, 13_800_000, 7, "Asus", "Core i5, RAM 16GB, SSD 512GB, màn 15.6 inch"),
    ("LT-DEL-01", "Laptop Dell Inspiron 14", "Laptop", 17_490_000, 15_200_000, 9, "Dell", "Core i5, RAM 16GB, SSD 512GB, màn 14 inch"),
    ("LT-LEN-01", "Laptop Lenovo IdeaPad Slim 3", "Laptop", 13_990_000, 12_000_000, 6, "Lenovo", "Ryzen 5, RAM 8GB, SSD 512GB, mỏng nhẹ 1.6kg"),
    ("LT-HP-01", "Laptop HP 15s", "Laptop", 14_490_000, 12_500_000, 5, "HP", "Core i5, RAM 8GB, SSD 512GB, màn 15.6 inch"),
    ("LT-ACE-01", "Laptop Acer Aspire 5", "Laptop", 16_290_000, 14_100_000, 8, "Acer", "Core i5, RAM 16GB, SSD 512GB, vỏ nhôm"),
    ("LT-MAC-01", "Laptop MacBook Air 13", "Laptop", 24_990_000, 22_400_000, 6, "Apple", "Chip M2, RAM 8GB, SSD 256GB, pin 18 giờ"),
    ("TB-SAM-01", "Máy tính bảng Samsung Galaxy Tab A9", "Máy tính bảng", 4_990_000, 4_200_000, 8, "Samsung", "Màn 8.7 inch, RAM 4GB, pin 5100mAh"),
    ("TB-IPA-01", "iPad 10.9 inch", "Máy tính bảng", 9_990_000, 8_900_000, 6, "Apple", "Chip A14, 64GB, hỗ trợ Apple Pencil"),
    ("TB-XIA-01", "Máy tính bảng Xiaomi Pad 6", "Máy tính bảng", 7_490_000, 6_400_000, 5, "Xiaomi", "Màn 11 inch 144Hz, Snapdragon 870"),
    ("DT-SAM-05", "Samsung Galaxy A55", "Điện thoại", 9_490_000, 7_800_000, 4, "Samsung", "Màn 6.6 inch, camera 50MP, chống nước IP67"),
    ("DT-IPH-01", "iPhone 15 128GB", "Điện thoại", 19_990_000, 18_200_000, 7, "Apple", "Chip A16, camera 48MP, cổng USB-C"),
    ("DT-XIA-01", "Xiaomi Redmi Note 13", "Điện thoại", 5_490_000, 4_600_000, 10, "Xiaomi", "Camera 108MP, sạc nhanh 33W, pin 5000mAh"),
    ("DT-OPP-01", "OPPO Reno 11F", "Điện thoại", 8_490_000, 7_200_000, 6, "OPPO", "Camera chân dung 64MP, sạc 67W"),
    ("DT-REA-01", "Realme C67", "Điện thoại", 4_690_000, 3_900_000, 9, "Realme", "Màn 90Hz, pin 5000mAh, sạc 33W"),
    ("CH-LOG-02", "Chuột Logitech M331", "Chuột", 290_000, 210_000, 25, "Logitech", "Không dây, nhấn im lặng, pin 24 tháng"),
    ("CH-LOG-03", "Chuột Logitech MX Master 3S", "Chuột", 2_490_000, 2_000_000, 8, "Logitech", "8000 DPI, cuộn MagSpeed, kết nối 3 thiết bị"),
    ("CH-RAZ-01", "Chuột Razer DeathAdder Essential", "Chuột", 590_000, 450_000, 12, "Razer", "Chuột chơi game có dây 6400 DPI"),
    ("CH-FOR-01", "Chuột không dây Forter V181", "Chuột", 150_000, 100_000, 30, "Forter", "Không dây 2.4GHz, giá rẻ"),
    ("CH-DAR-01", "Chuột Dareu EM908", "Chuột", 390_000, 290_000, 14, "Dareu", "Chuột gaming LED RGB 6000 DPI"),
    ("LC-RAZ-01", "Lót chuột Razer Gigantus", "Lót chuột", 390_000, 280_000, 14, "Razer", "Bề mặt vải, đế cao su chống trượt"),
    ("LC-LOG-01", "Lót chuột Logitech Desk Mat", "Lót chuột", 450_000, 330_000, 9, "Logitech", "Cỡ lớn 70x30cm, chống thấm"),
    ("LC-GEN-01", "Lót chuột cỡ lớn 80x30", "Lót chuột", 120_000, 70_000, 40, None, "Lót chuột kiêm lót bàn phím"),
    ("BP-KEY-01", "Bàn phím cơ Keychron K2", "Bàn phím", 1_890_000, 1_500_000, 3, "Keychron", "Switch Gateron, Bluetooth và dây, layout 75%"),
    ("BP-LOG-01", "Bàn phím Logitech K380", "Bàn phím", 790_000, 600_000, 15, "Logitech", "Bluetooth, kết nối 3 thiết bị, nhỏ gọn"),
    ("BP-DAR-01", "Bàn phím cơ Dareu EK87", "Bàn phím", 690_000, 520_000, 11, "Dareu", "TKL 87 phím, switch D"),
    ("BP-AKK-01", "Bàn phím cơ AKKO 3068", "Bàn phím", 1_590_000, 1_250_000, 7, "AKKO", "68 phím, 3 chế độ kết nối, hotswap"),
    ("SA-ANK-03", "Sạc Anker 20W", "Sạc", 350_000, 250_000, 30, "Anker", "Sạc nhanh PD 20W cho iPhone và Android"),
    ("SA-ANK-65", "Sạc Anker 65W", "Sạc", 990_000, 760_000, 2, "Anker", "GaN 65W, 3 cổng, sạc được laptop"),
    ("SA-SAM-01", "Sạc nhanh Samsung 25W", "Sạc", 450_000, 330_000, 18, "Samsung", "Super Fast Charging 25W"),
    ("SA-BAS-01", "Cáp sạc USB-C Baseus 1m", "Sạc", 120_000, 70_000, 50, "Baseus", "Cáp bện dù, sạc nhanh 100W"),
    ("SA-PIN-01", "Pin dự phòng Xiaomi 10000mAh", "Sạc", 490_000, 370_000, 16, "Xiaomi", "Sạc nhanh 22.5W, 2 cổng ra"),
    ("TN-BLU-A1", "Tai nghe Bluetooth A1", "Tai nghe", 350_000, 240_000, 12, None, "Pin 20 giờ, Bluetooth 5.3, chống nước IPX4"),
    ("TN-JBL-01", "Tai nghe JBL Tune 510", "Tai nghe", 490_000, 360_000, 6, "JBL", "Tai nghe chụp tai không dây, pin 40 giờ"),
    ("TN-SON-01", "Tai nghe Sony WH-CH520", "Tai nghe", 1_190_000, 920_000, 12, "Sony", "Chụp tai không dây, pin 50 giờ"),
    ("TN-APP-01", "Tai nghe Apple AirPods 3", "Tai nghe", 3_990_000, 3_500_000, 5, "Apple", "Âm thanh không gian, sạc MagSafe"),
    ("TN-SAM-01", "Tai nghe Samsung Galaxy Buds FE", "Tai nghe", 1_490_000, 1_150_000, 9, "Samsung", "Chống ồn chủ động ANC"),
    ("TN-XIA-01", "Tai nghe Xiaomi Redmi Buds 4", "Tai nghe", 590_000, 430_000, 20, "Xiaomi", "True wireless, pin 28 giờ kèm hộp"),
    ("TN-HAV-01", "Tai nghe chụp tai Havit H2002d", "Tai nghe", 450_000, 320_000, 14, "Havit", "Tai nghe gaming có micro"),
    ("PK-BAL-01", "Balo laptop chống sốc 15.6 inch", "Sạc", 450_000, 300_000, 15, None, "Ngăn chống sốc, chống nước nhẹ"),
    ("PK-HUB-01", "Hub USB-C 6 trong 1", "Sạc", 380_000, 260_000, 12, None, "HDMI 4K, USB 3.0, đọc thẻ SD"),
    ("PK-WEB-01", "Webcam Logitech C270", "Chuột", 690_000, 520_000, 10, "Logitech", "HD 720p, micro giảm ồn"),
]

# Ảnh chụp có sẵn trong static/img/products (nguồn Pexels và Wikimedia Commons, xem NGUON_ANH.md)
IMAGES = {
    "LT-ASU-01": "MT003", "DT-IPH-01": "DT003", "DT-SAM-05": "DT001", "DT-XIA-01": "DT002", "CH-FOR-01": "MT001",
    "BP-KEY-01": "MT002", "PK-WEB-01": "MT005", "SA-ANK-03": "PK005", "SA-BAS-01": "PK006", "SA-PIN-01": "PK007",
    "TN-BLU-A1": "PK001", "TN-SAM-01": "PK002", "TN-SON-01": "AT003", "TN-XIA-01": "AT004", "TN-JBL-01": "PK004",
    "TN-HAV-01": "PK003",
    # Ảnh từ Wikimedia Commons, tệp đặt theo mã sản phẩm (xem NGUON_ANH.md)
    "BP-AKK-01": "BP-AKK-01",
    "BP-DAR-01": "BP-DAR-01",
    "BP-LOG-01": "BP-LOG-01",
    "CH-DAR-01": "CH-DAR-01",
    "CH-LOG-02": "CH-LOG-02",
    "CH-LOG-03": "CH-LOG-03",
    "CH-RAZ-01": "CH-RAZ-01",
    "DT-OPP-01": "DT-OPP-01",
    "DT-REA-01": "DT-REA-01",
    "LC-GEN-01": "LC-GEN-01",
    "LC-LOG-01": "LC-LOG-01",
    "LC-RAZ-01": "LC-RAZ-01",
    "LT-ACE-01": "LT-ACE-01",
    "LT-DEL-01": "LT-DEL-01",
    "LT-HP-01": "LT-HP-01",
    "LT-LEN-01": "LT-LEN-01",
    "LT-MAC-01": "LT-MAC-01",
    "PK-BAL-01": "PK-BAL-01",
    "PK-HUB-01": "PK-HUB-01",
    "SA-ANK-65": "SA-ANK-65",
    "SA-SAM-01": "SA-SAM-01",
    "TB-IPA-01": "TB-IPA-01",
    "TB-SAM-01": "TB-SAM-01",
    "TB-XIA-01": "TB-XIA-01",
    "TN-APP-01": "TN-APP-01",
}

# Bảng A.4: 5 khách cố định (mã, họ tên, SĐT, điểm, tổng chi tiêu từ trước khi dùng hệ thống); còn lại sinh thêm
FIXED_CUSTOMERS = [
    ("KH0012", "Trần Văn Nam", "0912345678", 420, 31_450_000),
    ("KH0013", "Lê Thị Hoa", "0912300004", 35, 3_200_000),
    ("KH0021", "Phạm Quốc Bảo", "0912700551", 1_820, 64_800_000),
    ("KH0024", "Đỗ Thùy Linh", "0987100220", 0, 0),
    ("KH0027", "Hoàng Minh Quân", "0987200331", 260, 22_900_000),
]
OTHER_NAMES = ["Nguyễn Thu Hà", "Vũ Đức Anh", "Bùi Ngọc Trâm", "Đặng Hữu Phúc", "Ngô Bích Ngọc", "Phan Đức Huy",
               "Lý Thanh Tâm", "Trịnh Văn Sơn", "Mai Phương Thảo", "Hồ Quang Vinh", "Dương Thị Yến", "Tạ Minh Khôi",
               "Cao Thị Mỹ", "Lưu Gia Bảo", "Võ Hoài An"]

# Bảng A.5: mã, tên, liên hệ, các nhóm hàng cung cấp
SUPPLIERS = [
    ("NCC01", "Công ty Phân phối Minh Long", "Anh Hùng", ["Laptop", "Máy tính bảng"]),
    ("NCC02", "Công ty Điện thoại Việt", "Chị Mai", ["Điện thoại"]),
    ("NCC03", "Đại lý Phụ kiện Số", "Anh Tuấn", ["Chuột", "Bàn phím", "Lót chuột"]),
    ("NCC04", "Công ty Âm thanh Hòa Phát", "Chị Lan", ["Tai nghe"]),
    ("NCC05", "Nhà phân phối Sạc và Cáp An Phú", "Anh Phúc", ["Sạc"]),
]


def _password(env_key: str, default: str) -> str:
    return os.getenv(env_key, "").strip() or default


def _plan_history(rnd: random.Random, products: list[tuple], customers: list[str], start: datetime) -> list[dict]:
    """Sinh trước 60 hóa đơn: ngày giờ, khách, dòng hàng, phương thức thanh toán."""
    accessories = [p for p in products if p[2] not in ("Laptop", "Máy tính bảng", "Điện thoại")]
    devices = [p for p in products if p[2] in ("Laptop", "Máy tính bảng", "Điện thoại")]
    plans = []
    for i in range(HISTORY_INVOICES):
        day = start + timedelta(days=rnd.randrange(HISTORY_DAYS))
        at = datetime.combine(day.date(), time(rnd.randint(8, 20), rnd.randint(0, 59)))
        lines: dict[str, int] = defaultdict(int)
        if rnd.random() < 0.35:
            lines[rnd.choice(devices)[0]] += 1
        for _ in range(rnd.choice([1, 1, 2, 2, 3])):
            lines[rnd.choice(accessories)[0]] += rnd.choice([1, 1, 1, 2])
        plans.append({"at": at, "customer": rnd.choice(customers + [None] * 6), "lines": dict(lines),
                      "method": rnd.choice(["cash", "cash", "cash", "bank_transfer", "card"])})
    return sorted(plans, key=lambda p: p["at"])


def _enroll_faces(db, user: User) -> None:
    """Đăng ký Face ID cho một tài khoản từ ảnh trong scripts/face_samples/<tên đăng nhập>/.
    Máy chưa cài OpenCV hoặc không tải được mô hình thì bỏ qua, người dùng tự đăng ký ở trang Tài khoản."""
    folder = FACE_SAMPLES / user.username
    photos = sorted(p for p in folder.glob("*") if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"))
    if not photos:
        return
    try:
        for p in photos:
            db.add(FaceProfile(user_id=user.id, embedding=face.embed(p.read_bytes())))
    except (face.FaceError, face.FaceUnavailable, ImportError) as e:
        db.rollback()
        print(f"Bỏ qua đăng ký Face ID cho {user.username}: {e}")
        return
    db.commit()
    print(f"Đã đăng ký Face ID cho {user.username} từ {len(photos)} ảnh mẫu.")


def run(seed: int = SEED) -> None:
    rnd = random.Random(seed)
    Base.metadata.drop_all(engine)
    ensure_schema(engine)
    db = SessionLocal()
    try:
        users = {}
        for username, name, role, env_key, default, must_change in USERS:
            users[role] = User(username=username, full_name=name, role=role, must_change_password=must_change,
                               password_hash=hash_password(_password(env_key, default)))
            db.add(users[role])
        owner, staff = users["owner"], users["staff"]
        cats = {name: Category(name=name, name_en=CATEGORY_EN.get(name), default_vat_rate=10, default_warranty_months=12)
                for name, _ in CATEGORIES}
        serial_cat = {name for name, s in CATEGORIES if s}
        db.add_all(cats.values())
        db.flush()

        by_code: dict[str, Product] = {}
        for code, name, cat, sale, cost, _, brand, desc in PRODUCTS:
            img = IMAGES.get(code)
            p = Product(code=code, barcode=f"893{rnd.randrange(10 ** 9, 10 ** 10)}", name=name,
                        name_en=PRODUCT_EN.get(code, (None, None))[1], category_id=cats[cat].id, brand=brand, sale_price=sale, cost_price=cost, vat_rate=10,
                        warranty_months=12, stock=0, min_stock=5, track_serial=cat in serial_cat, description=desc,
                        image_url=f"/static/img/products/{img}.webp" if img else None)
            db.add(p)
            by_code[code] = p
        sups = {}
        for code, name, contact, groups in SUPPLIERS:
            sups[code] = Supplier(code=code, name=name, contact_name=contact, phone=f"028{rnd.randrange(10 ** 7):07d}",
                                  email=f"{code.lower()}@example.com", status="active")
            db.add(sups[code])
        db.flush()

        loyalty.ensure_tiers(db)
        customers = []
        fixed_codes = set()
        for code, name, phone, points, spent in FIXED_CUSTOMERS:
            c = Customer(code=code, name=name, phone=phone, email=None, address="TP. Hồ Chí Minh", total_spent=spent)
            db.add(c)
            db.flush()
            if points:
                loyalty.change_points(db, c, points, "adjust", note="Số dư đầu kỳ", user=owner)
            loyalty.recompute_tier(db, c)
            fixed_codes.add(code)
        used = {int(c[0][2:]) for c in FIXED_CUSTOMERS}
        free = [n for n in range(10, 40) if n not in used]
        for name, n in zip(OTHER_NAMES, free):
            c = Customer(code=f"KH{n:04d}", name=name, phone=f"09{rnd.randrange(10 ** 8):08d}",
                         email=f"khach{n}@example.com", address="TP. Hồ Chí Minh")
            db.add(c)
            customers.append(c)
        db.flush()
        loyalty.assign_missing_tiers(db)

        start = now() - timedelta(days=HISTORY_DAYS)
        plans = _plan_history(rnd, PRODUCTS, [c.code for c in customers], start)
        sold: dict[str, int] = defaultdict(int)
        for plan in plans:
            for code, qty in plan["lines"].items():
                sold[code] += qty

        # Phiếu nhập đầu kỳ cho từng nhà cung cấp: tồn mong muốn + số sẽ bán, hàng có serial kèm serial giả
        opening = start - timedelta(days=1)
        serial_seq = defaultdict(int)
        for sup_code, _, _, groups in SUPPLIERS:
            items = []
            for code, _, cat, _, cost, stock, _, _ in PRODUCTS:
                if cat not in groups:
                    continue
                qty = stock + sold[code]
                serials = []
                if cat in serial_cat:
                    for _ in range(qty):
                        serial_seq[code] += 1
                        serials.append(f"SN{code.replace('-', '')}{serial_seq[code]:04d}")
                items.append(PurchaseItemIn(product_id=by_code[code].id, quantity=qty, unit_cost=cost, serials=serials))
            purchasing.create(db, PurchaseOrderIn(supplier_id=sups[sup_code].id, items=items, confirm=True,
                                                  note="Tồn đầu kỳ"), owner, at=opening)

        # Khuyến mãi bảng A.6. Tai nghe giảm 10% chạy trong tháng hiện tại.
        today = now()
        month_end = today.replace(day=calendar.monthrange(today.year, today.month)[1], hour=23, minute=59, second=59)
        db.add_all([
            Promotion(code="TECH10", name="Giảm 500.000 hóa đơn từ 5 triệu", promo_type="fixed_amount", scope="invoice",
                      discount_value=500_000, min_invoice_amount=5_000_000, requires_code=True, usage_limit=100,
                      start_at=start, end_at=today + timedelta(days=90), created_by=owner.id),
            Promotion(code=None, name="Tai nghe giảm 10%", promo_type="percent", scope="category",
                      target_id=cats["Tai nghe"].id, discount_value=10, max_discount=150_000, requires_code=False,
                      start_at=today.replace(day=1, hour=0, minute=0, second=0), end_at=month_end, created_by=owner.id),
            Promotion(code="SAC20K", name="Giảm 20.000 cho sạc", promo_type="fixed_amount", scope="product",
                      target_id=by_code["SA-ANK-03"].id, discount_value=20_000, requires_code=True,
                      start_at=start, end_at=today + timedelta(days=90), created_by=owner.id),
        ])
        db.flush()

        # 60 hóa đơn lịch sử, dùng đúng nghiệp vụ bán hàng
        cust_by_code = {c.code: c for c in customers}
        for plan in plans:
            items = []
            for code, qty in plan["lines"].items():
                p = by_code[code]
                if p.track_serial:
                    from app.models import ProductSerial
                    from sqlalchemy import select
                    serials = db.scalars(select(ProductSerial).where(ProductSerial.product_id == p.id,
                                                                     ProductSerial.status == "in_stock")
                                         .order_by(ProductSerial.id).limit(qty)).all()
                    items += [InvoiceItemIn(product_id=p.id, quantity=1, serial_id=s.id) for s in serials]
                else:
                    items.append(InvoiceItemIn(product_id=p.id, quantity=qty))
            customer = cust_by_code.get(plan["customer"])
            data = InvoiceIn(customer_id=customer.id if customer else None, items=items,
                             payment_method=plan["method"], payment_confirmed=True)
            if plan["method"] == "card":
                data.payment_ref = f"POS{rnd.randint(100000, 999999)}"
            sales.checkout(db, data, rnd.choice([staff, staff, owner]), at=plan["at"])
        db.commit()
        for u in (users["owner"], users["admin"]):  # Face ID cho chủ cửa hàng và quản trị viên
            _enroll_faces(db, u)
        print(f"Đã tạo dữ liệu mẫu: {len(PRODUCTS)} sản phẩm, {len(customers) + len(FIXED_CUSTOMERS)} khách hàng, "
              f"{len(SUPPLIERS)} nhà cung cấp, {len(plans)} hóa đơn trong {HISTORY_DAYS} ngày.")
        print("Tài khoản: " + ", ".join(f"{u}/{_password(e, d)}" for u, _, _, e, d, _ in USERS)
              + " (admin phải đổi mật khẩu ở lần đăng nhập đầu)")
    finally:
        db.close()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # console Windows mặc định cp1252
    run()
