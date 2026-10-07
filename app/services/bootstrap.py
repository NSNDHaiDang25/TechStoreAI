"""Dữ liệu tham chiếu cần có trong mọi CSDL: hạng khách hàng (Thành viên, Bạc, Vàng).

Tham số cấu hình không cần tạo sẵn: chưa có dòng trong bảng settings thì dùng giá trị mặc định.
"""
from sqlalchemy.orm import Session

from app.services import loyalty


def ensure_reference_data(bind) -> None:
    with Session(bind) as db:
        loyalty.ensure_tiers(db)
        loyalty.assign_missing_tiers(db)
        db.commit()
