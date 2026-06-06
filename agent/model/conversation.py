from datetime import datetime, UTC

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        onupdate=lambda: datetime.now(UTC),
    )
