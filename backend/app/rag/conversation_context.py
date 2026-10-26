"""Lightweight conversation support — see the answer-generation task's
"Conversation context": no autonomous memory or agent loop, just a
persisted turn history used to resolve obvious pronoun references in a
follow-up question (e.g. "What calls it?" after "Explain
AuthService.login.").

Stored in the application database (SQLAlchemy, same ``Base``/engine as
app.indexing.metadata's manifest table) — small, relational, operational
data, not the code graph or vectors.
"""

import re
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, cast

from sqlalchemy import CursorResult, DateTime, String, Text, delete, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.database import Base

_PRONOUN_RE = re.compile(r"\b(it|this|that|its|these|those)\b", re.IGNORECASE)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ConversationRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class ConversationMessage(Base):
    """One turn in a conversation. ``repository_id`` is stored on every
    row (not just derived from the conversation) specifically so a
    conversation can never be read back under a different repository —
    see ``get_conversation_repository_id`` / the task's "Repository
    context must never cross conversations belonging to another
    repository."."""

    __tablename__ = "conversation_messages"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    repository_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    role: Mapped[str] = mapped_column(String, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    # The primary resolved symbol's qualified_name from an assistant
    # turn, if any — what a following pronoun ("it"/"that") most likely
    # refers to. None for user turns and for assistant turns that
    # resolved no symbol.
    referenced_qualified_name: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


def get_conversation_repository_id(session: Session, conversation_id: str) -> str | None:
    """The repository_id this conversation_id already belongs to, if
    any turn has been recorded for it yet — ``None`` for a brand-new
    conversation_id."""
    statement = (
        select(ConversationMessage.repository_id)
        .where(ConversationMessage.conversation_id == conversation_id)
        .limit(1)
    )
    return session.execute(statement).scalar_one_or_none()


def get_recent_turns(
    session: Session, *, conversation_id: str, repository_id: str, limit: int
) -> list[ConversationMessage]:
    """Chronological (oldest-first) recent turns, always scoped to both
    conversation_id *and* repository_id."""
    statement = (
        select(ConversationMessage)
        .where(
            ConversationMessage.conversation_id == conversation_id,
            ConversationMessage.repository_id == repository_id,
        )
        .order_by(ConversationMessage.created_at.desc())
        .limit(limit)
    )
    rows = list(session.scalars(statement))
    return list(reversed(rows))


def append_turn(
    session: Session,
    *,
    conversation_id: str,
    repository_id: str,
    role: ConversationRole,
    message: str,
    referenced_qualified_name: str | None = None,
) -> ConversationMessage:
    row = ConversationMessage(
        id=str(uuid.uuid4()),
        conversation_id=conversation_id,
        repository_id=repository_id,
        role=role.value,
        message=message,
        referenced_qualified_name=referenced_qualified_name,
    )
    session.add(row)
    session.commit()
    return row


def delete_conversation_messages_for_repository(session: Session, repository_id: str) -> int:
    """Remove every conversation turn recorded for this repository_id —
    see the integration-reliability task's "Repository deletion":
    "conversation messages" must be cleaned up alongside the other
    stores. Returns the number of rows removed."""
    result = cast(
        "CursorResult[Any]",
        session.execute(
            delete(ConversationMessage).where(ConversationMessage.repository_id == repository_id)
        ),
    )
    session.commit()
    return result.rowcount or 0


def resolve_follow_up_question(question: str, recent_turns: list[ConversationMessage]) -> str:
    """If the question contains an obvious pronoun/reference and a
    prior assistant turn resolved a symbol, append a plain-text
    clarification the deterministic entity extractor can pick up (see
    app.rag.entity_extractor's dotted-name pattern) — deliberately
    simple/deterministic, not an LLM call, per "Do not implement
    autonomous memory or agents."."""
    if not _PRONOUN_RE.search(question):
        return question
    for turn in reversed(recent_turns):
        if turn.role == ConversationRole.ASSISTANT.value and turn.referenced_qualified_name:
            return f"{question} (referring to {turn.referenced_qualified_name})"
    return question
