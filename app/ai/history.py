"""Lưu lịch sử tra cứu AI (trợ lý đa năng, chatbot tư vấn, hỏi đáp dữ liệu) theo từng người dùng."""
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import ChatMessage, ChatSession, User, now

KINDS = ("assistant", "advisor", "ask")
CONTEXT_TURNS = 10  # FR-AIA-08: 5 lượt hỏi - đáp gần nhất (10 tin nhắn) gửi kèm cho AI làm ngữ cảnh


class SessionNotFound(Exception):
    pass


def make_title(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= 60 else text[:57].rstrip() + "..."


def get_session(db: Session, user: User, session_id: int) -> ChatSession:
    s = db.get(ChatSession, session_id)
    if s is None or s.user_id != user.id:  # không cho xem lịch sử của người khác
        raise SessionNotFound
    return s


def get_or_create(db: Session, user: User, kind: str, session_id: int | None, first_message: str) -> ChatSession:
    if session_id:
        s = get_session(db, user, session_id)
        if s.kind != kind:
            raise SessionNotFound
        return s
    s = ChatSession(user_id=user.id, kind=kind, title=make_title(first_message))
    db.add(s)
    db.flush()
    return s


def recent_history(s: ChatSession, turns: int = CONTEXT_TURNS) -> list[dict]:
    return [{"role": m.role, "content": m.content} for m in s.messages[-turns:]]


def append_turn(db: Session, s: ChatSession, question: str, answer: str, meta: dict) -> ChatMessage:
    db.add(ChatMessage(session_id=s.id, role="user", content=question))
    reply = ChatMessage(session_id=s.id, role="assistant", content=answer, meta=meta)
    db.add(reply)
    s.updated_at = now()
    db.flush()
    return reply


def _search(stmt, q: str | None):
    """Lọc theo tiêu đề hoặc nội dung tin nhắn."""
    if not q or not q.strip():
        return stmt
    like = f"%{q.strip()}%"
    in_messages = select(ChatMessage.id).where(ChatMessage.session_id == ChatSession.id,
                                               ChatMessage.content.ilike(like)).exists()
    return stmt.where(or_(ChatSession.title.ilike(like), in_messages))


def _message_count():
    return (select(ChatMessage.session_id, func.count().label("n"))
            .group_by(ChatMessage.session_id).subquery())


def list_sessions(db: Session, user: User, kind: str, q: str | None = None, limit: int = 100) -> list[dict]:
    count = _message_count()
    stmt = (select(ChatSession, func.coalesce(count.c.n, 0))
            .outerjoin(count, count.c.session_id == ChatSession.id)
            .where(ChatSession.user_id == user.id, ChatSession.kind == kind))
    stmt = _search(stmt, q)
    rows = db.execute(stmt.order_by(ChatSession.updated_at.desc(), ChatSession.id.desc()).limit(limit)).all()
    return [{"id": s.id, "title": s.title, "kind": s.kind, "created_at": s.created_at,
             "updated_at": s.updated_at, "message_count": n} for s, n in rows]


def list_all_sessions(db: Session, kind: str | None, user_id: int | None, q: str | None,
                      page: int, size: int) -> dict:
    """Quản trị viên xem lịch sử hội thoại AI của mọi người dùng (chỉ đọc)."""
    count = _message_count()
    stmt = (select(ChatSession, User.full_name, User.role, func.coalesce(count.c.n, 0))
            .join(User, User.id == ChatSession.user_id)
            .outerjoin(count, count.c.session_id == ChatSession.id))
    if kind:
        stmt = stmt.where(ChatSession.kind == kind)
    if user_id:
        stmt = stmt.where(ChatSession.user_id == user_id)
    stmt = _search(stmt, q)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.execute(stmt.order_by(ChatSession.updated_at.desc(), ChatSession.id.desc())
                      .offset((page - 1) * size).limit(size)).all()
    return {"total": total, "items": [{
        "id": s.id, "title": s.title, "kind": s.kind, "user_id": s.user_id, "user_name": name, "user_role": role,
        "created_at": s.created_at, "updated_at": s.updated_at, "message_count": n} for s, name, role, n in rows]}


def session_detail(s: ChatSession) -> dict:
    return {"id": s.id, "title": s.title, "kind": s.kind, "created_at": s.created_at, "updated_at": s.updated_at,
            "messages": [{"id": m.id, "role": m.role, "content": m.content, "meta": m.meta,
                          "created_at": m.created_at} for m in s.messages]}
