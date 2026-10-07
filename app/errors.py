"""Quy ước phản hồi lỗi theo SRS mục 8.4.1.

Mọi lỗi trả về cùng cấu trúc:
    {"error": {"code": "OUT_OF_STOCK", "message": "...", "details": {...}}, "detail": "..."}

- code: chuỗi ổn định cho giao diện xử lý (OUT_OF_STOCK, RETURN_WINDOW_EXPIRED, RATE_LIMITED...).
- message: câu tiếng Việt hiển thị cho người dùng.
- detail: giữ lại khóa mặc định của FastAPI để giao diện cũ (static/app.js) và giao diện React vẫn đọc được.

Mã trạng thái theo bảng 8.12: 400 sai cú pháp, 401 chưa đăng nhập, 403 không đủ quyền, 404 không tìm thấy,
409 xung đột nghiệp vụ (hết hàng, quá hạn đổi trả...), 422 dữ liệu không qua kiểm tra, 429 quá nhiều yêu cầu,
503 dịch vụ phụ thuộc không sẵn sàng (AI tắt).
"""
import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

DEFAULT_CODES = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
    500: "INTERNAL_ERROR",
    503: "SERVICE_UNAVAILABLE",
}


class APIError(HTTPException):
    """HTTPException kèm mã lỗi ổn định (code) và chi tiết (details) cho giao diện."""

    def __init__(self, status_code: int, message: str, code: str | None = None, details: dict | None = None,
                 headers: dict | None = None):
        super().__init__(status_code=status_code, detail=message, headers=headers)
        self.code = code or DEFAULT_CODES.get(status_code, "ERROR")
        self.details = details


def error_body(status_code: int, message, code: str | None = None, details=None) -> dict:
    text = message if isinstance(message, str) else "Dữ liệu không hợp lệ"
    body = {"error": {"code": code or DEFAULT_CODES.get(status_code, "ERROR"), "message": text}}
    if details is not None:
        body["error"]["details"] = details
    body["detail"] = message  # tương thích ngược
    return body


def install(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException):
        body = error_body(exc.status_code, exc.detail, getattr(exc, "code", None), getattr(exc, "details", None))
        return JSONResponse(status_code=exc.status_code, content=jsonable_encoder(body),
                            headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        errors = jsonable_encoder(exc.errors(), custom_encoder={Exception: str})
        messages = [str(e.get("msg", "")).removeprefix("Value error, ") for e in errors]
        body = {"error": {"code": "VALIDATION_ERROR", "message": "; ".join(m for m in messages if m)
                          or "Dữ liệu không hợp lệ", "details": errors},
                "detail": errors}
        return JSONResponse(status_code=422, content=body)

    @app.exception_handler(ValueError)
    async def value_error(_: Request, exc: ValueError):
        return JSONResponse(status_code=400, content=error_body(400, str(exc)))
