from datetime import datetime
from importlib import import_module
from typing import TYPE_CHECKING

# cspell:ignore ondelete
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .approval import ApprovalBatch
    from .message import Message
    from .tool_invocation import ToolInvocation


class MessagePart(Base):
    __tablename__ = "message_parts"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    message_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("messages.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    type: Mapped[str] = mapped_column(String, nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tool_invocation_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("tool_invocations.id", ondelete="SET NULL"),
        nullable=True,
    )
    approval_batch_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey(
            "approval_batches.id",
            ondelete="SET NULL",
            name="fk_message_parts_approval_batch_id",
        ),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    message: Mapped["Message"] = relationship(
        "Message",
        back_populates="timeline_parts",
    )
    tool_invocation: Mapped["ToolInvocation | None"] = relationship(
        "ToolInvocation",
    )
    approval_batch: Mapped["ApprovalBatch | None"] = relationship(
        "ApprovalBatch",
    )


# Import approval model so importing Message -> MessagePart can configure mappers.
import_module(".approval", __package__)
