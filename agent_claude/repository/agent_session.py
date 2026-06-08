from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from model.agent_session import AgentSession


async def get_agent_session_by_conversation_id(
    session: AsyncSession,
    conversation_id: str,
) -> AgentSession | None:
    result = await session.execute(
        select(AgentSession).where(AgentSession.conversation_id == conversation_id)
    )
    return result.scalar_one_or_none()


async def upsert_agent_session(
    session: AsyncSession,
    *,
    conversation_id: str,
    sdk_session_id: str,
) -> AgentSession:
    row = await get_agent_session_by_conversation_id(session, conversation_id)
    now = datetime.now(UTC)
    if row is None:
        row = AgentSession(
            id=str(uuid4()),
            conversation_id=conversation_id,
            sdk_session_id=sdk_session_id,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
    else:
        row.sdk_session_id = sdk_session_id
        row.updated_at = now
    await session.flush()
    return row
