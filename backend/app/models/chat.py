import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ChatSession(Base):
    """One resume-building conversation.

    `id` doubles as the LangGraph thread_id, so this table answers "which sessions
    does this user have" without deserializing checkpoints.
    """

    __tablename__ = "chat_sessions"
    __table_args__ = (
        Index("ix_chat_sessions_user_updated", "user_id", "updated_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    title: Mapped[str] = mapped_column(String(200), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<ChatSession id={self.id} user_id={self.user_id}>"


class ChatMessage(Base):
    """One turn of the conversation, human or AI.

    The checkpoint holds the resume state; this holds what was actually said, so a
    resumed session can redraw the chat without replaying the graph.
    """

    __tablename__ = "chat_messages"
    __table_args__ = (
                                                           
        Index("ix_chat_messages_session_id", "session_id", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    session_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )

    role: Mapped[str] = mapped_column(String(16), nullable=False)                        

    content: Mapped[str] = mapped_column(Text, nullable=False)

                                                                                 
                                                           
    ui: Mapped[str | None] = mapped_column(String(16), nullable=True)
    options: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    def as_dict(self) -> dict:
        return {
            "role": self.role,
            "content": self.content,
            "ui": self.ui,
            "options": self.options or [],
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return f"<ChatMessage id={self.id} session={self.session_id} role={self.role}>"
