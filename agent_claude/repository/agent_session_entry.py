from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from model.agent_session_entry import AgentSessionEntry


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

    normalized_subpath = subpath or ""
    entry_uuids = {
        payload["uuid"]
        for payload in payloads
        if isinstance(payload.get("uuid"), str) and payload["uuid"]
    }
    existing_entry_uuids: set[str] = set()
    if entry_uuids:
        existing_result = await session.execute(
            select(AgentSessionEntry.entry_uuid).where(
                AgentSessionEntry.project_key == project_key,
                AgentSessionEntry.sdk_session_id == sdk_session_id,
                AgentSessionEntry.subpath == normalized_subpath,
                AgentSessionEntry.entry_uuid.in_(entry_uuids),
            )
        )
        existing_entry_uuids = set(existing_result.scalars().all())

    result = await session.execute(
        select(AgentSessionEntry.sequence_no)
        .where(
            AgentSessionEntry.project_key == project_key,
            AgentSessionEntry.sdk_session_id == sdk_session_id,
            AgentSessionEntry.subpath == normalized_subpath,
        )
        .order_by(AgentSessionEntry.sequence_no.desc())
        .limit(1)
    )
    last_sequence = result.scalar_one_or_none() or 0
    now = datetime.now(UTC)
    next_sequence = last_sequence
    for payload in payloads:
        entry_uuid = payload.get("uuid")
        if not isinstance(entry_uuid, str) or not entry_uuid:
            entry_uuid = None
        if entry_uuid in existing_entry_uuids:
            continue
        next_sequence += 1
        session.add(
            AgentSessionEntry(
                id=str(uuid4()),
                project_key=project_key,
                sdk_session_id=sdk_session_id,
                subpath=normalized_subpath,
                sequence_no=next_sequence,
                entry_uuid=entry_uuid,
                entry_payload=payload,
                created_at=now,
            )
        )
        if entry_uuid:
            existing_entry_uuids.add(entry_uuid)
    await session.flush()


async def load_session_entries(
    session: AsyncSession,
    *,
    sdk_session_id: str,
    project_key: str = "",
    subpath: str | None = None,
) -> list[dict[str, Any]]:
    normalized_subpath = subpath or ""
    result = await session.execute(
        select(AgentSessionEntry)
        .where(
            AgentSessionEntry.project_key == project_key,
            AgentSessionEntry.sdk_session_id == sdk_session_id,
            AgentSessionEntry.subpath == normalized_subpath,
        )
        .order_by(AgentSessionEntry.sequence_no.asc())
    )
    return [row.entry_payload for row in result.scalars().all()]
