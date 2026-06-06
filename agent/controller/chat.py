from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db_session
from schema.chat import ChatStreamRequest
from service.chat_run import ConversationRunConflict, create_chat_run
from service.run_events import stream_run_events


async def run_stream_chat(
    req: ChatStreamRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
):
    try:
        creation = await create_chat_run(session, req)
        await session.commit()
    except ConversationRunConflict as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Conversation already has an active run",
        ) from exc
    except Exception:
        await session.rollback()
        raise

    return StreamingResponse(
        stream_run_events(creation.run.id, after_event_id=0),
        media_type="text/event-stream",
    )
