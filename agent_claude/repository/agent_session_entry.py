from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from model.agent_session_entry import AgentSessionEntry


def _storage_session_id(
    *,
    project_key: str,
    sdk_session_id: str,
    subpath: str | None = None,
) -> str:
    if subpath:
        return f"{project_key}/{sdk_session_id}/{subpath}"
    return f"{project_key}/{sdk_session_id}"


async def append_session_entries(
    session: AsyncSession,
    *,
    sdk_session_id: str,
    payloads: list[dict[str, Any]],
    project_key: str = "",
    subpath: str | None = None,
) -> None:
    if not payloads:
        return

    storage_session_id = _storage_session_id(
        project_key=project_key,
        sdk_session_id=sdk_session_id,
        subpath=subpath,
    )
    result = await session.execute(
        select(AgentSessionEntry.sequence_no)
        .where(AgentSessionEntry.sdk_session_id == storage_session_id)
        .order_by(AgentSessionEntry.sequence_no.desc())
        .limit(1)
    )
    last_sequence = result.scalar_one_or_none() or 0
    now = datetime.now(UTC)
    for index, payload in enumerate(payloads, start=1):
        session.add(
            AgentSessionEntry(
                id=str(uuid4()),
                sdk_session_id=storage_session_id,
                sequence_no=last_sequence + index,
                entry_payload=payload,
                created_at=now,
            )
        )
    await session.flush()


async def load_session_entries(
    session: AsyncSession,
    *,
    sdk_session_id: str,
    project_key: str = "",
    subpath: str | None = None,
) -> list[dict[str, Any]]:
    storage_session_id = _storage_session_id(
        project_key=project_key,
        sdk_session_id=sdk_session_id,
        subpath=subpath,
    )
    result = await session.execute(
        select(AgentSessionEntry)
        .where(AgentSessionEntry.sdk_session_id == storage_session_id)
        .order_by(AgentSessionEntry.sequence_no.asc())
    )
    return [row.entry_payload for row in result.scalars().all()]
