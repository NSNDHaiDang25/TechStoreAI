from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.ai import assistant, history, service
from app.ai.client import GeminiClient, get_ai_client
from app.database import get_db
from app.models import ChatSession, User
from app.schemas import AIReportIn, AIReportPdfIn, ChatIn, CrossSellIn, QuestionIn, SessionRename
from app.security import ADMIN_ONLY, ALL_STAFF, ANY_ROLE, MANAGERS
from app.services import ai_log, app_settings, export

router = APIRouter(prefix="/api/ai", tags=["ai"])


@router.get("/status")
def ai_status(db: Session = Depends(get_db), client: GeminiClient = Depends(get_ai_client),
              _: User = Depends(ANY_ROLE)):
    """model = model đang dùng được (None nếu mọi model đều đang hết lượt); models = tình trạng từng model.
    switched_on = quản trị viên đang bật AI (ai_enabled); enabled = đã cấu hình khóa API."""
    info = client.status() if client.enabled else {"active_model": None, "models": []}
    cfg = app_settings.get_many(db, ["ai_enabled", "ai_prompt_version", "ai_rate_limit_per_hour"])
    return {"enabled": client.enabled, "switched_on": cfg["ai_enabled"], "model": info["active_model"],
            "models": info["models"], "advisor_prompt_version": cfg["ai_prompt_version"],
            "rate_limit_per_hour": cfg["ai_rate_limit_per_hour"]}


@router.get("/logs")
def ai_logs(feature: str | None = None, status: str | None = None, user_id: int | None = None,
            page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=200),
            db: Session = Depends(get_db), user: User = Depends(ANY_ROLE)):
    """Nhật ký gọi AI. Quản trị viên, chủ cửa hàng xem tất cả; nhân viên chỉ xem lượt của mình."""
    return ai_log.list_logs(db, user, feature, status, user_id, page, size)


def _session_for(db: Session, user: User, kind: str, session_id: int | None, text: str) -> ChatSession:
    try:
        return history.get_or_create(db, user, kind, session_id, text)
    except history.SessionNotFound:
        raise HTTPException(404, "Không tìm thấy cuộc trò chuyện")


@router.post("/assistant")
def assistant_chat(data: ChatIn, db: Session = Depends(get_db), client: GeminiClient = Depends(ai_log.configured_client),
                   user: User = Depends(ALL_STAFF), _: User = Depends(ai_log.ai_guard)):
    """Trợ lý đa năng: AI tự gọi công cụ tra cứu phù hợp với vai trò người dùng."""
    session = _session_for(db, user, "assistant", data.session_id, data.message)
    result = assistant.reply(db, client, user, data.message, history.recent_history(session, 10))
    ai_log.record(db, user, "assistant", data.message, result, model=client.model)
    meta = {k: result.get(k) for k in ("suggestions", "tools", "source", "warning", "latency_ms", "model", "period", "period_label")}
    reply = history.append_turn(db, session, data.message, result["answer"], meta)
    db.commit()
    return {**result, "session_id": session.id, "session_title": session.title, "message_id": reply.id}


@router.post("/advisor")
def advisor(data: ChatIn, version: str | None = Query(None, pattern="^v[123]$"),
            db: Session = Depends(get_db), client: GeminiClient = Depends(ai_log.configured_client),
            user: User = Depends(ALL_STAFF), _: User = Depends(ai_log.ai_guard)):
    session = _session_for(db, user, "advisor", data.session_id, data.message)
    version = version or app_settings.get(db, "ai_prompt_version")
    result = service.advise(db, client, data.message, history.recent_history(session), version)
    ai_log.record(db, user, "advisor", data.message, result, prompt_version=version, model=client.model)
    meta = {k: result.get(k) for k in ("suggestions", "removed", "source", "version", "warning", "latency_ms", "model")}
    reply = history.append_turn(db, session, data.message, result["answer"], meta)
    db.commit()
    return {**result, "session_id": session.id, "session_title": session.title, "message_id": reply.id}


@router.post("/advisor/cross-sell")
def advisor_cross_sell(data: CrossSellIn, db: Session = Depends(get_db),
                       client: GeminiClient = Depends(ai_log.configured_client),
                       user: User = Depends(ALL_STAFF), _: User = Depends(ai_log.ai_guard)):
    """FR-AIA-07: gợi ý phụ kiện đi kèm dựa trên giỏ hàng hiện tại (màn hình bán hàng)."""
    result = service.cross_sell(db, client, data.product_ids)
    ai_log.record(db, user, "cross_sell", result.pop("question"), result, prompt_version="v1", model=client.model)
    db.commit()
    return result


@router.post("/report")
def ai_report(data: AIReportIn, db: Session = Depends(get_db), client: GeminiClient = Depends(ai_log.configured_client),
              user: User = Depends(MANAGERS), _: User = Depends(ai_log.ai_guard)):
    result = service.sales_report(db, client, data.date_from, data.date_to)
    ai_log.record(db, user, "report", f"Báo cáo {data.date_from or ''} - {data.date_to or ''}".strip(), result,
                  prompt_version="v1", model=client.model, response=result.get("markdown"))
    db.commit()
    return result


@router.post("/report/pdf")
def ai_report_pdf(data: AIReportPdfIn, db: Session = Depends(get_db), _: User = Depends(MANAGERS)):
    """FR-AIR-06: xuất báo cáo AI đang xem ra PDF (nội dung đã lưu trong ai_logs khi sinh báo cáo)."""
    store = app_settings.get(db, "store_name") or "TechStoreAI"
    period = f"Kỳ {data.date_from or '?'} đến {data.date_to or '?'}" if (data.date_from or data.date_to) else ""
    pdf = export.markdown_pdf(f"Báo cáo doanh thu - {store}", " · ".join(x for x in (period, "Nhận xét do AI soạn từ "
                              "số liệu hệ thống tính sẵn") if x), data.markdown)
    name = f"bao-cao-ai-{data.date_from or ''}-{data.date_to or ''}.pdf".replace("--", "-")
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.post("/ask")
def ask(data: QuestionIn, db: Session = Depends(get_db), client: GeminiClient = Depends(ai_log.configured_client),
        user: User = Depends(MANAGERS), _: User = Depends(ai_log.ai_guard)):
    session = _session_for(db, user, "ask", data.session_id, data.question)
    result = service.ask_data(db, client, data.question)
    ai_log.record(db, user, "qa", data.question, result, prompt_version="v1", model=client.model,
                  generated_sql=result.get("sql"))
    meta = {k: result.get(k) for k in ("period", "period_label", "source", "warning", "latency_ms", "model",
                                       "sql", "columns", "row_count", "truncated")}
    meta["rows"] = (result.get("rows") or [])[:50]  # lịch sử chỉ giữ 50 dòng đầu của bảng kết quả
    reply = history.append_turn(db, session, data.question, result["answer"], meta)
    db.commit()
    return {**result, "session_id": session.id, "session_title": session.title, "message_id": reply.id}


# ---------------- Lịch sử tra cứu ----------------
def _check_kind(kind: str, user: User) -> None:
    if kind not in history.KINDS:
        raise HTTPException(400, "Loại lịch sử không hợp lệ")
    if kind == "ask" and user.role == "staff":
        raise HTTPException(403, "Bạn không có quyền thực hiện chức năng này")


def _own_session(db: Session, user: User, session_id: int) -> ChatSession:
    try:
        return history.get_session(db, user, session_id)
    except history.SessionNotFound:
        raise HTTPException(404, "Không tìm thấy cuộc trò chuyện")


@router.get("/sessions")
def list_sessions(kind: str = "advisor", q: str | None = None, db: Session = Depends(get_db),
                  user: User = Depends(ALL_STAFF)):
    _check_kind(kind, user)
    return history.list_sessions(db, user, kind, q)


@router.get("/sessions/{session_id}")
def get_session(session_id: int, db: Session = Depends(get_db), user: User = Depends(ALL_STAFF)):
    return history.session_detail(_own_session(db, user, session_id))


@router.patch("/sessions/{session_id}")
def rename_session(session_id: int, data: SessionRename, db: Session = Depends(get_db),
                   user: User = Depends(ALL_STAFF)):
    s = _own_session(db, user, session_id)
    s.title = history.make_title(data.title)
    db.commit()
    return {"id": s.id, "title": s.title}


@router.delete("/sessions/{session_id}")
def delete_session(session_id: int, db: Session = Depends(get_db), user: User = Depends(ALL_STAFF)):
    db.delete(_own_session(db, user, session_id))
    db.commit()
    return {"ok": True}


@router.delete("/sessions")
def clear_sessions(kind: str = "advisor", db: Session = Depends(get_db), user: User = Depends(ALL_STAFF)):
    _check_kind(kind, user)
    sessions = db.scalars(select(ChatSession).where(ChatSession.user_id == user.id, ChatSession.kind == kind)).all()
    for s in sessions:
        db.delete(s)
    db.commit()
    return {"deleted": len(sessions)}


@router.get("/conversations")
def all_conversations(kind: str | None = None, user_id: int | None = None, q: str | None = None,
                      page: int = Query(1, ge=1), size: int = Query(30, ge=1, le=100),
                      db: Session = Depends(get_db), _: User = Depends(ADMIN_ONLY)):
    """Quản trị viên xem lịch sử hội thoại AI của mọi người dùng, chỉ đọc (không chat, không sửa, không xóa)."""
    if kind and kind not in history.KINDS:
        raise HTTPException(400, "Loại lịch sử không hợp lệ")
    return history.list_all_sessions(db, kind, user_id, q, page, size)


@router.get("/conversations/{session_id}")
def conversation_detail(session_id: int, db: Session = Depends(get_db), _: User = Depends(ADMIN_ONLY)):
    s = db.get(ChatSession, session_id)
    if s is None:
        raise HTTPException(404, "Không tìm thấy cuộc trò chuyện")
    owner = db.get(User, s.user_id)
    return {**history.session_detail(s), "user_name": owner.full_name if owner else None,
            "user_role": owner.role if owner else None}
