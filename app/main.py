import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import errors
from app.ai.client import reply_lang
from app.config import settings
from app.database import engine, ensure_schema
from app.routers import (aftersales, ai, auth, catalog, customers, inventory, invoices, loyalty, notifications, payments,
                         product_import, promotions, purchasing, reports, system)
from app.services.audit import client_ip

logging.basicConfig(level=logging.INFO)

async def _expire_pending_loop() -> None:
    """BR-26: mỗi phút hủy các hóa đơn chờ chuyển khoản quá hạn và hoàn tồn kho (ngoài việc kiểm tra khi gọi API)."""
    from app.database import SessionLocal
    from app.services import sales
    while True:
        await asyncio.sleep(60)
        try:
            with SessionLocal() as db:
                if sales.expire_pending(db):
                    db.commit()
        except Exception:  # noqa: BLE001 - vòng nền không được chết vì một lỗi
            logging.getLogger(__name__).exception("Lỗi khi hủy hóa đơn chờ thanh toán quá hạn")


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_schema(engine)
    task = asyncio.create_task(_expire_pending_loop())
    yield
    task.cancel()


app = FastAPI(
    title="TechStoreAI - Hệ thống quản lý bán hàng tích hợp AI",
    version="1.0.0",
    description="Quản lý sản phẩm, khách hàng, hóa đơn, nhập hàng, tồn kho, báo cáo và trợ lý AI (Gemini).",
    lifespan=lifespan,
)


@app.middleware("http")
async def remember_client_ip(request: Request, call_next):
    """Lưu IP người gọi để ghi vào audit_logs. Sau proxy (Render, nginx) IP thật nằm trong X-Forwarded-For."""
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    token = client_ip.set((forwarded or (request.client.host if request.client else ""))[:45] or None)
    # Giao diện gửi kèm ngôn ngữ đang chọn để AI trả lời cùng ngôn ngữ
    lang_token = reply_lang.set("en" if request.headers.get("accept-language", "").lower().startswith("en") else "vi")
    try:
        return await call_next(request)
    finally:
        client_ip.reset(token)
        reply_lang.reset(lang_token)


errors.install(app)  # cấu trúc lỗi chung {"error": {"code", "message", "details"}} theo SRS 8.4.1


# product_import đứng trước catalog để /api/products/import-template không bị hiểu là /api/products/{product_id}
for r in (auth, aftersales, product_import, catalog, customers, inventory, invoices, loyalty, notifications, payments, promotions,
          purchasing, reports, ai, system):
    app.include_router(r.router)
app.include_router(reports.export_router)  # đường dẫn /api/export/* theo SRS bảng 8.10


@app.get("/api/health")
def health():
    return {"status": "ok"}


class RevalidatedStaticFiles(StaticFiles):
    """Buộc trình duyệt hỏi lại server (ETag, trả 304 nếu không đổi) để không dùng app.js / style.css cũ sau khi cập nhật."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


app.mount("/static", RevalidatedStaticFiles(directory=settings.STATIC_DIR), name="static")
settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=settings.UPLOAD_DIR), name="uploads")


NO_CACHE = {"Cache-Control": "no-cache"}
REACT_INDEX = settings.STATIC_DIR / "app" / "index.html"   # bản build React (frontend/, `npm run build`)
CLASSIC_INDEX = settings.STATIC_DIR / "index.html"          # giao diện cũ (HTML/JS thuần), giữ để dự phòng


def _spa_index() -> FileResponse:
    return FileResponse(REACT_INDEX if REACT_INDEX.exists() else CLASSIC_INDEX, headers=NO_CACHE)


@app.get("/", include_in_schema=False)
def index():
    return _spa_index()


@app.get("/classic", include_in_schema=False)
def classic():
    return FileResponse(CLASSIC_INDEX, headers=NO_CACHE)


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    # Trình duyệt tự gọi /favicon.ico ở các trang không khai báo icon (ví dụ /docs)
    return FileResponse(settings.STATIC_DIR / "img" / "favicon.svg", media_type="image/svg+xml")


@app.get("/{full_path:path}", include_in_schema=False)
def spa_fallback(full_path: str):
    """Giao diện React dùng đường dẫn thật (/pos, /reports...): mọi đường dẫn không phải API trả về index.html."""
    if full_path.startswith(("api/", "static/", "uploads/")):
        raise HTTPException(404, "Không tìm thấy")
    return _spa_index()
