from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from core.database import AsyncSessionLocal
from model.agent_run import AgentRun
from schema.chat import ChatStreamRequest, ChatStreamResumeRequest
from service.chat_run import ConversationRunConflict, create_chat_run
from service.run_events import stream_run_events


async def run_stream_chat(
    req: ChatStreamRequest,
):
    async with AsyncSessionLocal() as session:
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
        stream_run_events(
            creation.run.id,
            after_event_id=0,
            wait_for_new_events=True,
        ),
        media_type="text/event-stream",
    )


async def resume_stream_chat(
    req: ChatStreamResumeRequest,
):
    async with AsyncSessionLocal() as session:
        run = await session.get(AgentRun, req.run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    return StreamingResponse(
        stream_run_events(
            req.run_id,
            after_event_id=req.after_event_id,
            wait_for_new_events=True,
        ),
        media_type="text/event-stream",
    )
