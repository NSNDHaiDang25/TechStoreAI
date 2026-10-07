"""Hạng khách hàng (UC-16)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import CustomerTier, Setting, User, now
from app.schemas import TiersIn
from app.security import ALL_STAFF, MANAGERS
from app.services import audit, loyalty

router = APIRouter(prefix="/api", tags=["loyalty"])


@router.get("/customer-tiers")
def list_tiers(db: Session = Depends(get_db), _: User = Depends(ALL_STAFF)):
    out = loyalty.tiers_out(db)
    db.commit()
    return out


@router.put("/customer-tiers")
def update_tiers(data: TiersIn, db: Session = Depends(get_db), user: User = Depends(MANAGERS)):
    """Sửa ngưỡng và hệ số điểm của các hạng, sau đó tính lại hạng mọi khách (FR-LOY-01, 02)."""
    tiers = {t.id: t for t in loyalty.ensure_tiers(db)}
    before = loyalty.tiers_out(db)
    for item in data.tiers:
        t = tiers.get(item.id)
        if t is None:
            raise HTTPException(404, f"Không tìm thấy hạng id {item.id}")
        t.min_total_spent = item.min_total_spent
        t.points_multiplier = item.points_multiplier
    ordered = sorted(tiers.values(), key=lambda t: t.min_total_spent)
    if ordered[0].min_total_spent != 0:
        db.rollback()
        raise HTTPException(400, "Hạng thấp nhất phải có ngưỡng 0 đồng")
    if len({t.min_total_spent for t in ordered}) != len(ordered):
        db.rollback()
        raise HTTPException(400, "Các hạng phải có ngưỡng chi tiêu khác nhau")
    # Giữ bảng settings (tier_silver_min, tier_gold_min) khớp với bảng hạng
    for name, key, _ in loyalty.DEFAULT_TIERS:
        t = next((x for x in ordered if x.name == name), None)
        if key and t is not None:
            row = db.get(Setting, key) or Setting(key=key, description=f"Tổng chi tiêu để lên hạng {name}")
            row.value, row.updated_by, row.updated_at = str(t.min_total_spent), user.id, now()
            db.add(row)
    db.flush()
    loyalty.recompute_all(db)
    audit.log(db, user, "TIER_UPDATE", "customer_tiers", None, old=before, new=loyalty.tiers_out(db))
    db.commit()
    return loyalty.tiers_out(db)
