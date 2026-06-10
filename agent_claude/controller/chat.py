from datetime import UTC, datetime
from uuid import uuid4

from fastapi import HTTPException, Response
from fastapi.responses import JSONResponse, StreamingResponse

from core.database import AsyncSessionLocal
from model.conversation import Conversation
from repository.conversation import (
    create_conversation as create_conversation_row,
    delete_conversation as delete_conversation_row,
    get_conversation_by_id,
    list_conversations as list_conversation_rows,
    update_conversation_title as update_conversation_title_row,
)
from repository import message as message_repository
from schema.chat import (
    ApprovalDecisionsRequest,
    ChatConversation,
    ChatStreamResumeRequest,
    ConversationMessagesResponse,
    DeleteConversationRequest,
    DeleteConversationResponse,
    StreamChatRequest,
    UpdateConversationTitleRequest,
)
from service.chat import stream_chat
from service import approval_gate, history
from service import run_manager
from service.run_events import stream_run_events


async def run_stream_chat(req: StreamChatRequest) -> StreamingResponse:
    return StreamingResponse(
        run_manager.start_chat_run(req),
        media_type="text/event-stream",
    )


async def resume_chat_stream(req: ChatStreamResumeRequest) -> StreamingResponse:
    return StreamingResponse(
        stream_run_events(
            run_id=req.run_id,
            after_event_id=req.after_event_id,
        ),
        media_type="text/event-stream",
    )


async def get_conversation_messages(conversation_id: str) -> ConversationMessagesResponse:
    async with AsyncSessionLocal() as session:
        response = await history.get_conversation_messages(
            session=session,
            conversation_id=conversation_id,
        )
    return JSONResponse(response.model_dump(by_alias=True, exclude_none=True))


async def create_conversation() -> ChatConversation:
    now = datetime.now(UTC)
    async with AsyncSessionLocal() as session:
        conversation = await create_conversation_row(
            session,
            Conversation(
                id=str(uuid4()),
                title="New chat",
                created_at=now,
                updated_at=now,
            ),
        )
        await session.commit()
    return history.project_conversation(conversation)


async def get_conversations_list() -> list[ChatConversation]:
    async with AsyncSessionLocal() as session:
        conversations = await list_conversation_rows(session)
    return [history.project_conversation(conversation) for conversation in conversations]


async def update_conversation_title(
    req: UpdateConversationTitleRequest,
) -> ChatConversation:
    async with AsyncSessionLocal() as session:
        conversation = await update_conversation_title_row(
            session,
            conversation_id=req.conversation_id,
            title=req.title,
        )
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        await session.commit()
    return history.project_conversation(conversation)


async def delete_conversation(req: DeleteConversationRequest) -> DeleteConversationResponse:
    async with AsyncSessionLocal() as session:
        conversation = await get_conversation_by_id(session, req.conversation_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        await delete_conversation_row(session, conversation)
        await session.commit()
    return DeleteConversationResponse(conversation_id=req.conversation_id, deleted=True)


async def unsupported_stream_resume() -> JSONResponse:
    return JSONResponse(
        {"detail": "Claude agent service does not support run resume"},
        status_code=410,
    )


async def unsupported_approval_decisions(batch_id: str) -> JSONResponse:
    return JSONResponse(
        {"detail": "Claude agent service does not support approvals"},
        status_code=410,
    )


async def edit_message(message_id: str, content: str) -> JSONResponse:
    if not content.strip():
        raise HTTPException(status_code=400, detail="Message content cannot be blank")

    async with AsyncSessionLocal() as session:
        try:
            message = await message_repository.edit_user_message(
                session,
                message_id=message_id,
                content=content,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="Message not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        await session.commit()

    projected = history._to_chat_message(message)
    return JSONResponse(projected.model_dump(by_alias=True, exclude_none=True))


async def submit_approval_decisions(
    batch_id: str,
    req: ApprovalDecisionsRequest,
) -> StreamingResponse:
    return StreamingResponse(
        approval_gate.submit_approval_decisions(batch_id, req),
        media_type="text/event-stream",
    )


async def cancel_chat_stream(message_id: str) -> Response:
    await run_manager.cancel_run_by_assistant_message_id(message_id)
    return Response(status_code=204)
