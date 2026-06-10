from datetime import datetime
from importlib import import_module
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Index, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .agent_run import AgentRun


class ApprovalBatch(Base):
    __tablename__ = "approval_batches"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    message_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    resolution_source: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    run: Mapped["AgentRun"] = relationship(
        "AgentRun",
        back_populates="approval_batches",
    )
    requests: Mapped[list["ApprovalRequest"]] = relationship(
        "ApprovalRequest",
        back_populates="approval_batch",
        cascade="all, delete-orphan",
    )


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"
    __table_args__ = (
        Index("ix_approval_requests_batch_id", "approval_batch_id"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    approval_batch_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("approval_batches.id", ondelete="CASCADE"),
        nullable=False,
    )
    tool_invocation_id: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )
    tool_name: Mapped[str] = mapped_column(String, nullable=False)
    args: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    decision: Mapped[str] = mapped_column(String, nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    approval_batch: Mapped["ApprovalBatch"] = relationship(
        "ApprovalBatch",
        back_populates="requests",
    )


import_module(".agent_run", __package__)
