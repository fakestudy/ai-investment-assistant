from collections.abc import Callable
from typing import Any

from claude_agent_sdk.types import SessionKey, SessionStoreEntry
from sqlalchemy.ext.asyncio import AsyncSession

from repository.agent_session_entry import append_session_entries, load_session_entries


class PostgresSessionStore:
    def __init__(self, session_factory: Callable[[], AsyncSession]) -> None:
        self.session_factory = session_factory

    async def append(
        self,
        key: SessionKey,
        entries: list[SessionStoreEntry],
    ) -> None:
        if not entries:
            return

        async with self.session_factory() as session:
            await append_session_entries(
                session,
                project_key=key["project_key"],
                sdk_session_id=key["session_id"],
                subpath=key.get("subpath"),
                payloads=[dict(entry) for entry in entries],
            )
            await session.commit()

    async def load(self, key: SessionKey) -> list[dict[str, Any]] | None:
        async with self.session_factory() as session:
            entries = await load_session_entries(
                session,
                project_key=key["project_key"],
                sdk_session_id=key["session_id"],
                subpath=key.get("subpath"),
            )
        return entries or None
