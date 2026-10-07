"""Sinh mã chứng từ theo SRS bảng 1.5: HD-yyyyMMdd-nnnn, PN-yyyyMMdd-nnn, DT-yyyyMMdd-nnn, BH-yyyyMMdd-nnn.

Số thứ tự tăng dần trong ngày, lấy số lớn nhất đã dùng cộng 1 nên không dùng lại mã của chứng từ đã hủy (BR-23).
Hai quầy lập cùng lúc: SQLite chỉ cho một giao dịch ghi tại một thời điểm, cột code có ràng buộc UNIQUE
nên trường hợp xấu nhất là một bên nhận lỗi và thử lại (xem invoices.create_with_retry).
"""
import re
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session


def next_code(db: Session, model, prefix: str, at: datetime, width: int = 3) -> str:
    base = f"{prefix}-{at:%Y%m%d}-"
    used = db.scalars(select(model.code).where(model.code.like(f"{base}%"))).all()
    nums = [int(m.group(1)) for c in used if (m := re.fullmatch(rf"{re.escape(base)}(\d+)", c))]
    return f"{base}{max(nums, default=0) + 1:0{width}d}"
