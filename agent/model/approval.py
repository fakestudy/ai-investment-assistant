from datetime import datetime
from importlib import import_module
from typing import TYPE_CHECKING, Any, Literal

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .agent_run import AgentRun

ApprovalBatchStatus = Literal["pending", "resolved", "expired"]
ApprovalResolutionSource = Literal["manual", "timeout"]
ApprovalRequestDecision = Literal["pending", "approved", "rejected", "expired"]


class ApprovalBatch(Base):
    __tablename__ = "approval_batches"
    __table_args__ = (
        UniqueConstraint(
            "agent_run_id",
            "sequence",
            name="uq_approval_batches_agent_run_sequence",
        ),
        UniqueConstraint(
            "agent_run_id",
            "interrupt_id",
            name="uq_approval_batches_agent_run_interrupt",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    agent_run_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    assistant_message_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    interrupt_id: Mapped[str] = mapped_column(String, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[ApprovalBatchStatus] = mapped_column(String, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    resolution_source: Mapped[ApprovalResolutionSource | None] = mapped_column(
        String,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    agent_run: Mapped["AgentRun"] = relationship(
        "AgentRun",
        back_populates="approval_batches",
    )
    requests: Mapped[list["ApprovalRequest"]] = relationship(
        "ApprovalRequest",
        back_populates="approval_batch",
        cascade="all, delete-orphan",
        order_by="ApprovalRequest.order_index",
    )


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"
    __table_args__ = (
        UniqueConstraint(
            "approval_batch_id",
            "order_index",
            name="uq_approval_requests_batch_order",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    approval_batch_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("approval_batches.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    tool_invocation_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("tool_invocations.id", ondelete="CASCADE"),
        nullable=False,
    )
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    tool_name: Mapped[str] = mapped_column(String, nullable=False)
    args: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    decision: Mapped[ApprovalRequestDecision] = mapped_column(
        String,
        nullable=False,
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    approval_batch: Mapped["ApprovalBatch"] = relationship(
        "ApprovalBatch",
        back_populates="requests",
    )


# Import run model so approval relationships can configure when Message imports parts.
import_module(".agent_run", __package__)
