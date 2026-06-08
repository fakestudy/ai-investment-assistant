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
            "project_key",
            "sdk_session_id",
            "subpath",
            "sequence_no",
            unique=True,
        ),
        Index(
            "ix_agent_session_entries_session_entry_uuid",
            "project_key",
            "sdk_session_id",
            "subpath",
            "entry_uuid",
            unique=True,
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_key: Mapped[str] = mapped_column(String, nullable=False)
    sdk_session_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    subpath: Mapped[str] = mapped_column(String, nullable=False, default="")
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    entry_uuid: Mapped[str | None] = mapped_column(String, nullable=True)
    entry_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
