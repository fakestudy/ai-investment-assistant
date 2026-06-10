from datetime import datetime
from importlib import import_module
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .agent_run_event import AgentRunEvent
    from .approval import ApprovalBatch


ACTIVE_RUN_STATUSES = (
    "queued",
    "running",
    "awaiting_approval",
    "resume_queued",
    "resuming",
)


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    assistant_message_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String, nullable=False)
    last_event_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    events: Mapped[list["AgentRunEvent"]] = relationship(
        "AgentRunEvent",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="AgentRunEvent.id",
    )
    approval_batches: Mapped[list["ApprovalBatch"]] = relationship(
        "ApprovalBatch",
        back_populates="run",
        cascade="all, delete-orphan",
    )


import_module(".agent_run_event", __package__)
import_module(".approval", __package__)
