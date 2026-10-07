"""Ghi ai_logs cho mỗi lượt gọi AI (BR-44), giới hạn lượt gọi mỗi giờ, bật / tắt AI theo cấu hình."""
import re
from datetime import timedelta

from fastapi import Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.client import get_ai_client
from app.ai.sanitizer import scrub
from app.database import get_db
from app.errors import APIError
from app.models import AILog, User, now
from app.security import get_current_user
from app.services import app_settings

_PHONE = re.compile(r"(?<!\d)(?:\+?84|0)(\d{2})[\s.\-]?(\d{3})[\s.\-]?(\d{3})(\d)(?!\d)")
_EMAIL = re.compile(r"([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")


def mask_sensitive(text: str | None) -> str:
    """BR-42 / NFR-DAT-01: che số điện thoại và email trước khi lưu nhật ký."""
    if not text:
        return ""
    text = _PHONE.sub(lambda m: f"0{m.group(1)}*****{m.group(4)}", text)
    return _EMAIL.sub(lambda m: f"{m.group(1)}***@{m.group(2)}", text)


def status_of(result: dict) -> str:
    if result.get("status"):  # dịch vụ đã xác định trạng thái (rejected_sql, timeout, invalid_format...)
        return result["status"]
    if result.get("source") == "ai":
        return "success"
    warning = (result.get("warning") or "").lower()
    if not warning or "chưa cấu hình" in warning:
        return "fallback"  # chưa cấu hình khóa API: trả lời bằng chế độ dự phòng
    if "429" in warning or "hết lượt" in warning or "quá tải" in warning or "hạn mức" in warning:
        return "rate_limited"
    if "timeout" in warning or "quá thời gian" in warning or "thời gian chờ" in warning:
        return "timeout"
    if "json" in warning or "định dạng" in warning:
        return "invalid_format"
    return "error"


def record(db: Session, user: User, feature: str, question: str, result: dict, *, prompt_version: str = "-",
           model: str | None = None, generated_sql: str | None = None, response: str | None = None) -> AILog:
    log = AILog(user_id=user.id, feature=feature, prompt_version=(prompt_version or "-")[:10],
                model_name=(result.get("model") or model or "-")[:50], question=scrub(question)[:4000],
                generated_sql=generated_sql, response=mask_sensitive(response if response is not None
                                                                      else result.get("answer"))[:8000],
                status=status_of(result), latency_ms=result.get("latency_ms"),
                retry_count=int(result.get("retry_count") or 0))
    db.add(log)
    return log


def ai_guard(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> User:
    """Chặn khi AI đang tắt (ai_enabled) hoặc người dùng đã gọi quá ai_rate_limit_per_hour lượt trong 1 giờ."""
    cfg = app_settings.get_many(db, ["ai_enabled", "ai_rate_limit_per_hour"])
    if not cfg["ai_enabled"]:
        raise APIError(503, "Tính năng AI đang tắt. Liên hệ quản trị viên để bật lại", "AI_DISABLED")
    limit = cfg["ai_rate_limit_per_hour"]
    if limit:
        used = db.scalar(select(func.count(AILog.id)).where(AILog.user_id == user.id,
                                                            AILog.created_at >= now() - timedelta(hours=1)))
        if used >= limit:
            oldest = db.scalar(select(func.min(AILog.created_at)).where(
                AILog.user_id == user.id, AILog.created_at >= now() - timedelta(hours=1)))
            wait = max(1, int(((oldest + timedelta(hours=1)) - now()).total_seconds() // 60) + 1) if oldest else 60
            raise APIError(429, f"Bạn đã dùng hết {limit} lượt AI trong 1 giờ, thử lại sau khoảng {wait} phút",
                           "RATE_LIMITED", {"limit": limit, "retry_after_minutes": wait},
                           headers={"Retry-After": str(wait * 60)})
    return user


def list_logs(db: Session, user: User, feature: str | None, status: str | None, user_id: int | None,
              page: int, size: int) -> dict:
    stmt = select(AILog)
    if user.role == "staff":
        stmt = stmt.where(AILog.user_id == user.id)  # bảng 4.2: nhân viên chỉ xem lượt của mình
    elif user_id:
        stmt = stmt.where(AILog.user_id == user_id)
    if feature:
        stmt = stmt.where(AILog.feature == feature)
    if status:
        stmt = stmt.where(AILog.status == status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(AILog.id.desc()).offset((page - 1) * size).limit(size)).all()
    summary = dict(db.execute(select(AILog.status, func.count(AILog.id)).group_by(AILog.status)).all()) \
        if user.role != "staff" else {}
    avg = db.scalar(select(func.avg(AILog.latency_ms)).where(AILog.status == "success")) if user.role != "staff" else None
    return {"total": total, "summary": summary, "avg_latency_ms": int(avg) if avg else None, "items": [{
        "id": r.id, "user_name": r.user.full_name if r.user else None, "feature": r.feature,
        "prompt_version": r.prompt_version, "model_name": r.model_name, "question": r.question,
        "generated_sql": r.generated_sql, "response": r.response, "status": r.status, "latency_ms": r.latency_ms,
        "retry_count": r.retry_count, "created_at": r.created_at} for r in rows]}


def configured_client(db: Session = Depends(get_db), client=Depends(get_ai_client)):
    """Áp tham số AI quản trị viên đã sửa trong bảng settings (UC-08) cho client dùng chung, không cần khởi động lại."""
    from app.models import Setting
    if db.get(Setting, "ai_model_name") is not None:
        model = app_settings.get(db, "ai_model_name").strip()
        if model and model != client.model:
            client.model = model
            if hasattr(client, "models"):
                client.models = list(dict.fromkeys([model, *client.models]))
    if db.get(Setting, "ai_timeout_seconds") is not None:
        client.timeout = float(app_settings.get(db, "ai_timeout_seconds"))
    if db.get(Setting, "ai_max_retries") is not None:
        client.max_retries = app_settings.get(db, "ai_max_retries")
    return client
