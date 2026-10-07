"""Hạng khách hàng và điểm tích lũy (SRS 5.6, BR-10 đến BR-14, BR-35)."""
import math
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Customer, CustomerTier, LoyaltyTransaction, User
from app.services import app_settings

BASE_TIER = "Thành viên"
DEFAULT_TIERS = [(BASE_TIER, None, 1.0), ("Bạc", "tier_silver_min", 1.2), ("Vàng", "tier_gold_min", 1.5)]


def ensure_tiers(db: Session) -> list[CustomerTier]:
    """Tạo ba hạng mặc định nếu bảng còn trống (CSDL mới, CSDL nâng cấp từ bản cũ, CSDL test)."""
    tiers = list(db.scalars(select(CustomerTier).order_by(CustomerTier.min_total_spent)))
    if tiers:
        return tiers
    values = app_settings.get_many(db, ["tier_silver_min", "tier_gold_min"])
    for name, key, mult in DEFAULT_TIERS:
        db.add(CustomerTier(name=name, min_total_spent=values[key] if key else 0, points_multiplier=mult))
    db.flush()
    return list(db.scalars(select(CustomerTier).order_by(CustomerTier.min_total_spent)))


def tier_for(db: Session, total_spent: int) -> CustomerTier:
    tiers = ensure_tiers(db)
    best = tiers[0]
    for t in tiers:
        if total_spent >= t.min_total_spent:
            best = t
    return best


def recompute_tier(db: Session, customer: Customer) -> None:
    """BR-13: hạng tăng khi đạt ngưỡng, giảm khi tổng chi tiêu giảm do đổi trả, hủy."""
    customer.tier_id = tier_for(db, customer.total_spent).id


def assign_missing_tiers(db: Session) -> None:
    for c in db.scalars(select(Customer).where(Customer.tier_id.is_(None))):
        recompute_tier(db, c)


def recompute_all(db: Session) -> None:
    for c in db.scalars(select(Customer)):
        recompute_tier(db, c)


def multiplier(db: Session, customer: Customer) -> Decimal:
    tier = db.get(CustomerTier, customer.tier_id) if customer.tier_id else tier_for(db, customer.total_spent)
    # Đổi float sang Decimal qua chuỗi: 1759 * 1.2 phải ra 2110.8 chứ không phải 2110.7999...
    return Decimal(str(round(tier.points_multiplier, 4)))


def points_for(db: Session, customer: Customer | None, total_amount: int) -> int:
    """BR-10: 1 điểm cho mỗi points_per_vnd đồng, nhân hệ số hạng, làm tròn xuống. Khách lẻ không tích điểm."""
    if customer is None or total_amount <= 0:
        return 0
    per = app_settings.get(db, "points_per_vnd")
    return int(math.floor((total_amount // per) * multiplier(db, customer)))


def change_points(db: Session, customer: Customer, points: int, txn_type: str, *, invoice_id: int | None = None,
                  note: str | None = None, user: User | None = None) -> int:
    """Cộng (dương) hoặc trừ (âm) điểm, ghi loyalty_transactions. Điểm không âm: trừ quá số dư thì chỉ trừ hết."""
    if points < 0 and customer.loyalty_points + points < 0:
        points = -customer.loyalty_points
    if points == 0:
        return 0
    customer.loyalty_points += points
    db.add(LoyaltyTransaction(customer_id=customer.id, invoice_id=invoice_id, txn_type=txn_type, points=points,
                              balance_after=customer.loyalty_points, note=note,
                              created_by=user.id if user else None))
    return points


def history(db: Session, customer_id: int, limit: int = 100) -> list[dict]:
    rows = db.scalars(select(LoyaltyTransaction).where(LoyaltyTransaction.customer_id == customer_id)
                      .order_by(LoyaltyTransaction.id.desc()).limit(limit))
    return [{"id": t.id, "invoice_id": t.invoice_id, "txn_type": t.txn_type, "points": t.points,
             "balance_after": t.balance_after, "note": t.note, "created_at": t.created_at} for t in rows]


def tiers_out(db: Session) -> list[dict]:
    counts = dict(db.execute(select(Customer.tier_id, func.count(Customer.id)).group_by(Customer.tier_id)).all())
    return [{"id": t.id, "name": t.name, "min_total_spent": t.min_total_spent,
             "points_multiplier": t.points_multiplier, "customer_count": counts.get(t.id, 0)}
            for t in ensure_tiers(db)]


def sync_tiers_from_settings(db: Session) -> None:
    """Sửa ngưỡng hạng ở màn hình cấu hình thì cập nhật bảng customer_tiers và tính lại hạng mọi khách."""
    values = app_settings.get_many(db, ["tier_silver_min", "tier_gold_min"])
    tiers = {t.name: t for t in ensure_tiers(db)}
    for name, key, _ in DEFAULT_TIERS:
        if key and name in tiers:
            tiers[name].min_total_spent = values[key]
    db.flush()
    recompute_all(db)
