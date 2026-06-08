from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class AgentSessionEntry(Base):
    __tablename__ = "agent_session_entries"
    __table_args__ = (
        Index(
            "ix_agent_session_entries_session_sequence",
            "sdk_session_id",
            "sequence_no",
            unique=True,
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    sdk_session_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    entry_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
