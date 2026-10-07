"""Tính tiền hóa đơn theo SRS 3.4 và BR-01 đến BR-13 (FR-SAL-05).

Thứ tự tính:
1. Thành tiền gốc mỗi dòng = đơn giá (đã gồm VAT) x số lượng; tạm tính = tổng các dòng.
2. Khuyến mãi cấp dòng (sản phẩm, nhóm hàng): mỗi dòng chỉ áp khuyến mãi giảm nhiều tiền nhất (BR-06).
3. Khuyến mãi cấp hóa đơn: tối đa một, voucher khách nhập hoặc khuyến mãi tự động tốt nhất (BR-05).
4. Giảm tay (chỉ để tương thích bản cũ) và tiền dùng điểm (BR-12, tối đa 50% giá trị sau khuyến mãi).
5. Các khoản giảm cấp hóa đơn được phân bổ cho từng dòng theo tỷ lệ thành tiền, làm tròn đến đồng,
   dòng cuối nhận phần chênh lệch làm tròn, để đổi trả một dòng hoàn đúng số khách đã trả cho dòng đó.
6. VAT dòng = (thành tiền - giảm giá) x VAT / (100 + VAT), làm tròn; VAT hóa đơn = tổng VAT các dòng (BR-04).
7. Điểm dự kiến = phần nguyên(phải trả / 10.000) x hệ số hạng, làm tròn xuống (BR-10).
"""
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import Customer, Product, ProductSerial, Promotion, now
from app.services import app_settings, loyalty


class PricingError(Exception):
    """Giỏ hàng không hợp lệ (voucher sai, dùng quá điểm, giảm quá tổng tiền...)."""


def round_div(a: int, b: int) -> int:
    """Chia làm tròn nửa lên với số nguyên không âm (tránh round() kiểu ngân hàng của Python)."""
    return (2 * a + b) // (2 * b)


@dataclass
class Line:
    product: Product
    quantity: int
    unit_price: int
    serial: ProductSerial | None = None
    line_total: int = 0
    line_promo: int = 0
    line_promo_name: str | None = None
    line_promo_id: int | None = None
    allocated: int = 0
    vat_amount: int = 0

    @property
    def discount_amount(self) -> int:
        return self.line_promo + self.allocated

    @property
    def net_total(self) -> int:
        return self.line_total - self.discount_amount


@dataclass
class Cart:
    lines: list[Line]
    customer: Customer | None
    subtotal: int = 0
    line_promo_total: int = 0
    invoice_promo: Promotion | None = None
    invoice_promo_amount: int = 0
    manual_discount: int = 0
    points_used: int = 0
    points_discount: int = 0
    points_max: int = 0
    total: int = 0
    vat_amount: int = 0
    points_earned: int = 0
    warnings: list[str] = field(default_factory=list)
    below_cost: list[str] = field(default_factory=list)

    @property
    def promo_discount(self) -> int:
        return self.line_promo_total + self.invoice_promo_amount + self.manual_discount

    @property
    def discount(self) -> int:
        return self.promo_discount + self.points_discount

    def applied_promotions(self) -> list[dict]:
        out = {}
        for ln in self.lines:
            if ln.line_promo_id:
                p = out.setdefault(ln.line_promo_id, {"id": ln.line_promo_id, "name": ln.line_promo_name,
                                                      "scope": "line", "amount": 0})
                p["amount"] += ln.line_promo
        if self.invoice_promo:
            out[self.invoice_promo.id] = {"id": self.invoice_promo.id, "name": self.invoice_promo.name,
                                          "code": self.invoice_promo.code, "scope": "invoice",
                                          "amount": self.invoice_promo_amount}
        return list(out.values())

    def summary(self) -> dict:
        return {
            "subtotal": self.subtotal, "promo_discount": self.promo_discount, "points_discount": self.points_discount,
            "discount": self.discount, "total": self.total, "vat_amount": self.vat_amount,
            "revenue_net": self.total - self.vat_amount, "points_used": self.points_used,
            "points_max": self.points_max, "points_earned": self.points_earned,
            "promotions": self.applied_promotions(), "warnings": self.warnings + self.below_cost,
            "lines": [{"product_id": ln.product.id, "product_code": ln.product.code, "product_name": ln.product.name,
                       "serial_id": ln.serial.id if ln.serial else None,
                       "serial_no": ln.serial.serial_no if ln.serial else None,
                       "quantity": ln.quantity, "unit_price": ln.unit_price, "line_total": ln.line_total,
                       "line_promo": ln.line_promo, "promo_name": ln.line_promo_name, "allocated": ln.allocated,
                       "discount_amount": ln.discount_amount, "net_total": ln.net_total,
                       "vat_rate": ln.product.vat_rate, "vat_amount": ln.vat_amount} for ln in self.lines],
        }


# ---------------------------------------------------------------- Khuyến mãi
def refresh_expired(db: Session, at: datetime | None = None) -> None:
    """FR-PRM-07: khuyến mãi quá end_at tự chuyển expired."""
    at = at or now()
    for p in db.scalars(select(Promotion).where(Promotion.status == "active", Promotion.end_at < at)):
        p.status = "expired"


def promo_problem(p: Promotion, base_amount: int, at: datetime, own_usage: bool = False) -> str | None:
    """Lý do khuyến mãi không áp được (BR-07), None nếu hợp lệ. own_usage: hóa đơn đang sửa đã giữ một lượt."""
    if p.status == "paused":
        return "Khuyến mãi đang tạm dừng"
    if p.status == "expired" or at > p.end_at:
        return "Khuyến mãi đã hết hạn"
    if at < p.start_at:
        return f"Khuyến mãi bắt đầu từ {p.start_at:%d/%m/%Y %H:%M}"
    if p.usage_limit is not None and p.used_count - (1 if own_usage else 0) >= p.usage_limit:
        return "Khuyến mãi đã hết lượt sử dụng"
    if base_amount < (p.min_invoice_amount or 0):
        return f"Hóa đơn cần tối thiểu {p.min_invoice_amount:,}đ để dùng khuyến mãi này".replace(",", ".")
    return None


def promo_amount(p: Promotion, amount: int, quantity: int = 1) -> int:
    """BR-08: phần trăm có thể giới hạn max_discount; số tiền không vượt giá trị được giảm.
    Khuyến mãi số tiền cấp sản phẩm / nhóm hàng tính trên mỗi đơn vị sản phẩm."""
    if amount <= 0:
        return 0
    if p.promo_type == "percent":
        value = round_div(amount * p.discount_value, 100)
        if p.max_discount:
            value = min(value, p.max_discount)
    else:
        value = p.discount_value * (quantity if p.scope in ("product", "category") else 1)
    return max(0, min(value, amount))


def find_voucher(db: Session, code: str) -> Promotion:
    p = db.scalar(select(Promotion).where(Promotion.code == code.strip().upper()))
    if p is None:
        raise PricingError(f"Mã khuyến mãi '{code.strip().upper()}' không tồn tại")
    return p


def _applies_to(p: Promotion, product: Product) -> bool:
    return (p.scope == "product" and p.target_id == product.id) or \
           (p.scope == "category" and product.category_id is not None and p.target_id == product.category_id)


# ---------------------------------------------------------------- Tính giỏ hàng
def compute(db: Session, lines: list[Line], customer: Customer | None, *, promo_code: str | None = None,
            points_used: int = 0, manual_discount: int = 0, manual_percent: float | None = None,
            at: datetime | None = None, exclude_promotion_usage: int | None = None) -> Cart:
    """Tính toàn bộ số tiền của giỏ. exclude_promotion_usage: id khuyến mãi mà chính hóa đơn đang sửa đã giữ
    một lượt dùng, không tính lượt đó khi kiểm tra usage_limit."""
    at = at or now()
    cart = Cart(lines=lines, customer=customer)
    for ln in lines:
        ln.line_total = ln.unit_price * ln.quantity
    cart.subtotal = sum(ln.line_total for ln in lines)

    candidates = list(db.scalars(select(Promotion).where(
        Promotion.status == "active", Promotion.requires_code.is_(False),
        Promotion.start_at <= at, Promotion.end_at >= at)))
    voucher = find_voucher(db, promo_code) if promo_code and promo_code.strip() else None
    if voucher is not None:
        problem = promo_problem(voucher, cart.subtotal, at, own_usage=voucher.id == exclude_promotion_usage)
        if problem:
            raise PricingError(f"Mã {voucher.code}: {problem}")  # FR-PRM-06: báo lý do voucher không hợp lệ

    def usable(p: Promotion) -> bool:
        if p.usage_limit is None:
            return True
        used = p.used_count - (1 if p.id == exclude_promotion_usage else 0)
        return used < p.usage_limit

    # 2. Khuyến mãi cấp dòng: chọn mức giảm tiền lớn nhất cho mỗi dòng (BR-06)
    line_promos = [p for p in candidates if p.scope in ("product", "category") and usable(p)
                   and cart.subtotal >= (p.min_invoice_amount or 0)]
    if voucher is not None and voucher.scope in ("product", "category"):
        line_promos.append(voucher)
        if not any(_applies_to(voucher, ln.product) for ln in lines):
            raise PricingError(f"Mã {voucher.code} không áp dụng cho sản phẩm nào trong giỏ")
    for ln in lines:
        best, best_amount = None, 0
        for p in line_promos:
            if _applies_to(p, ln.product):
                amount = promo_amount(p, ln.line_total, ln.quantity)
                if amount > best_amount:
                    best, best_amount = p, amount
        if best:
            ln.line_promo, ln.line_promo_name, ln.line_promo_id = best_amount, best.name, best.id
    cart.line_promo_total = sum(ln.line_promo for ln in lines)
    after_line = cart.subtotal - cart.line_promo_total

    # 3. Một khuyến mãi cấp hóa đơn: voucher nếu có, ngược lại khuyến mãi tự động giảm nhiều nhất (BR-05)
    if voucher is not None and voucher.scope == "invoice":
        cart.invoice_promo, cart.invoice_promo_amount = voucher, promo_amount(voucher, after_line)
    elif voucher is None or voucher.scope != "invoice":
        best, best_amount = None, 0
        for p in candidates:
            if p.scope == "invoice" and promo_problem(p, cart.subtotal, at, p.id == exclude_promotion_usage) is None:
                amount = promo_amount(p, after_line)
                if amount > best_amount:
                    best, best_amount = p, amount
        cart.invoice_promo, cart.invoice_promo_amount = best, best_amount
    after_promo = after_line - cart.invoice_promo_amount

    # 4. Giảm tay (bản cũ) rồi dùng điểm
    manual = manual_discount
    if manual_percent is not None:
        manual = round_div(int(after_promo * manual_percent * 100), 10_000)
    if manual > after_promo:
        raise PricingError("Giảm giá không được lớn hơn tổng tiền hàng")
    cart.manual_discount = manual
    after_manual = after_promo - manual

    cfg = app_settings.get_many(db, ["point_value_vnd", "points_max_percent"])
    point_value = cfg["point_value_vnd"]
    if customer is not None and point_value > 0:
        cap_money = after_promo * cfg["points_max_percent"] // 100
        cart.points_max = min(customer.loyalty_points, cap_money // point_value, after_manual // point_value)
    if points_used:
        if customer is None:
            raise PricingError("Khách lẻ không dùng được điểm, hãy chọn khách hàng")
        if points_used > cart.points_max:
            # UC-22 luồng 2a: vượt số điểm đang có hoặc vượt 50% giá trị sau khuyến mãi thì tự hạ về mức tối đa
            why = (f"khách chỉ có {customer.loyalty_points} điểm" if cart.points_max == customer.loyalty_points
                   else f"tối đa {cfg['points_max_percent']}% giá trị hóa đơn sau khuyến mãi")
            cart.warnings.append(f"Đã tự hạ số điểm dùng từ {points_used} xuống {cart.points_max} ({why})")
            points_used = cart.points_max
        cart.points_used = points_used
        cart.points_discount = points_used * point_value

    # 5. Phân bổ các khoản giảm cấp hóa đơn cho từng dòng
    to_allocate = cart.invoice_promo_amount + cart.manual_discount + cart.points_discount
    bases = [ln.line_total - ln.line_promo for ln in lines]
    base_sum = sum(bases)
    if to_allocate > base_sum:
        raise PricingError("Giảm giá không được lớn hơn tổng tiền hàng")
    remaining = to_allocate
    for i, ln in enumerate(lines):
        if i == len(lines) - 1:
            ln.allocated = remaining
        else:
            ln.allocated = round_div(to_allocate * bases[i], base_sum) if base_sum else 0
            remaining -= ln.allocated

    # 6. VAT tách ra từ giá đã gồm VAT
    for ln in lines:
        rate = ln.product.vat_rate or 0
        ln.vat_amount = round_div(ln.net_total * rate, 100 + rate) if rate else 0
    cart.total = sum(ln.net_total for ln in lines)
    cart.vat_amount = sum(ln.vat_amount for ln in lines)

    # 7. Điểm dự kiến và cảnh báo bán dưới giá vốn (BR-03)
    cart.points_earned = loyalty.points_for(db, customer, cart.total)
    for ln in lines:
        if ln.product.cost_price and ln.net_total < ln.product.cost_price * ln.quantity:
            cart.below_cost.append(f"'{ln.product.name}' bán {ln.net_total // ln.quantity:,}đ/sp sau giảm, "
                                   f"thấp hơn giá vốn {ln.product.cost_price:,}đ".replace(",", "."))
    return cart


def active_promotions(db: Session, at: datetime | None = None) -> list[Promotion]:
    at = at or now()
    return list(db.scalars(select(Promotion).where(
        Promotion.status == "active", Promotion.start_at <= at, Promotion.end_at >= at,
        or_(Promotion.usage_limit.is_(None), Promotion.used_count < Promotion.usage_limit))
        .order_by(Promotion.end_at)))
