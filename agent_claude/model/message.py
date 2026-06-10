from datetime import datetime
from importlib import import_module
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .conversation import Conversation
    from .message_part import MessagePart
    from .tool_invocation import ToolInvocation


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    seq: Mapped[int] = mapped_column(
        BigInteger,
        Identity(always=False),
        nullable=False,
        unique=True,
    )
    conversation_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    reasoning: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    conversation: Mapped["Conversation"] = relationship(
        "Conversation",
        back_populates="messages",
    )
    tool_invocations: Mapped[list["ToolInvocation"]] = relationship(
        "ToolInvocation",
        back_populates="message",
        cascade="all, delete-orphan",
        order_by="ToolInvocation.created_at",
    )
    timeline_parts: Mapped[list["MessagePart"]] = relationship(
        "MessagePart",
        back_populates="message",
        cascade="all, delete-orphan",
        order_by="MessagePart.order_index",
    )


import_module(".message_part", __package__)
import_module(".tool_invocation", __package__)
