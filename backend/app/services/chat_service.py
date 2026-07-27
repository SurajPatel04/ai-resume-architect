import logging
import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatMessage, ChatSession

logger = logging.getLogger(__name__)

TITLE_MAX = 60

async def ensure_session(db: AsyncSession, session_id: str, user_id: uuid.UUID, title: str) -> bool:
    """Create the session row if new. False means it belongs to someone else.

    session_id is client-supplied, so this doubles as the ownership gate.
    """
    existing = await db.get(ChatSession, session_id)
    if existing:
        return existing.user_id == user_id

    db.add(ChatSession(id=session_id, user_id=user_id, title=title[:TITLE_MAX] or "New resume"))
    await db.commit()
    return True

async def add_message(
    db: AsyncSession,
    session_id: str,
    role: str,
    content: str,
    ui: str | None = None,
    options: list | None = None,
) -> None:
    db.add(ChatMessage(
        session_id=session_id,
        role=role,
        content=content,
        ui=ui,
        options=options or None,
    ))
                                                          
    await db.execute(
        update(ChatSession)
        .where(ChatSession.id == session_id)
        .values(updated_at=func.now())
    )
    await db.commit()

async def owns_session(db: AsyncSession, session_id: str, user_id: uuid.UUID) -> bool:
    session = await db.get(ChatSession, session_id)
    return bool(session and session.user_id == user_id)

async def list_sessions(db: AsyncSession, user_id: uuid.UUID, limit: int = 50) -> list[dict]:
    rows = await db.scalars(
        select(ChatSession)
        .where(ChatSession.user_id == user_id)
        .order_by(ChatSession.updated_at.desc())
        .limit(limit)
    )
    return [
        {"session_id": s.id, "title": s.title, "updated_at": s.updated_at.isoformat()}
        for s in rows
    ]

async def get_messages(db: AsyncSession, session_id: str, user_id: uuid.UUID) -> list[dict] | None:
    """The session's transcript, or None if it isn't this user's."""
    session = await db.get(ChatSession, session_id)
    if not session or session.user_id != user_id:
        return None

    rows = await db.scalars(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.id)
    )
    return [m.as_dict() for m in rows]
