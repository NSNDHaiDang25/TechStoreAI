"""API nhóm tồn kho theo SRS bảng 8.9: /api/inventory/low-stock, /movements, /adjust.

Dùng lại logic sẵn có (catalog, reports) để hai đường dẫn cũ và mới luôn trả kết quả như nhau.
"""
from fastapi import APIRouter, Depends, Query
from pydantic import Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.routers.catalog import adjust_product_stock, list_movements
from app.routers.reports import _with_images
from app.schemas import StockAdjustIn
from app.security import ALL_STAFF, MANAGERS
from app.services import reports

router = APIRouter(prefix="/api/inventory", tags=["inventory"])


class InventoryAdjustIn(StockAdjustIn):
    product_id: int = Field(gt=0)


@router.get("/low-stock")
def low_stock(db: Session = Depends(get_db), _: User = Depends(ALL_STAFF)):
    """FR-STK-02: sản phẩm dưới ngưỡng (nhân viên được xem; không có giá vốn trong kết quả)."""
    return _with_images(db, reports.low_stock(db))


@router.get("/movements")
def movements(product_id: int | None = None, type: str | None = None,
              date_from: str | None = None, date_to: str | None = None,
              page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=200),
              db: Session = Depends(get_db), user: User = Depends(MANAGERS)):
    """FR-STK-05: thẻ kho (bảng 8.9 ghi vai trò C)."""
    return list_movements(product_id, type, date_from, date_to, page, size, db, user)


@router.post("/adjust")
def adjust(data: InventoryAdjustIn, db: Session = Depends(get_db), user: User = Depends(MANAGERS)):
    """FR-STK-04: kiểm kê, điều chỉnh tồn có lý do (ghi stock_movements loại adjust)."""
    return adjust_product_stock(data.product_id, StockAdjustIn(new_stock=data.new_stock, note=data.note), db, user)
