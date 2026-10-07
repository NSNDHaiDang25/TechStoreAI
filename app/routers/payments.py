from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.schemas import VietQRIn
from app.security import ALL_STAFF
from app.services import app_settings
from app.services.qr import clean_transfer_content, qr_svg, vietqr_payload

router = APIRouter(prefix="/api/payments", tags=["payments"])


def _bank(db: Session) -> dict:
    return app_settings.get_many(db, ["store_name", "bank_bin", "bank_name", "bank_account", "bank_account_name"])


@router.get("/config")
def payment_config(db: Session = Depends(get_db), _: User = Depends(ALL_STAFF)):
    """Tài khoản nhận tiền lấy từ bảng settings (chủ cửa hàng sửa ở màn hình Cấu hình)."""
    b = _bank(db)
    return {"shop_name": b["store_name"], "bank_name": b["bank_name"], "account_no": b["bank_account"],
            "account_name": b["bank_account_name"], "is_demo": b["bank_account"] == "0123456789"}


@router.post("/vietqr")
def create_vietqr(data: VietQRIn, db: Session = Depends(get_db), _: User = Depends(ALL_STAFF)):
    """Mã VietQR cho khách quét bằng app ngân hàng: đã điền sẵn số tài khoản, số tiền, nội dung."""
    b = _bank(db)
    payload = vietqr_payload(b["bank_bin"], b["bank_account"], data.amount, data.content)
    return {"payload": payload, "svg": qr_svg(payload), "bank_name": b["bank_name"], "account_no": b["bank_account"],
            "account_name": b["bank_account_name"], "amount": data.amount,
            "content": clean_transfer_content(data.content), "is_demo": b["bank_account"] == "0123456789"}
