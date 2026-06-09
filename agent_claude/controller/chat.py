from datetime import UTC, datetime
from uuid import uuid4

from fastapi import HTTPException
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
from schema.chat import (
    ChatConversation,
    ConversationMessagesResponse,
    DeleteConversationRequest,
    DeleteConversationResponse,
    StreamChatRequest,
    UpdateConversationTitleRequest,
)
from service.chat import stream_chat
from service import history


async def run_stream_chat(req: StreamChatRequest) -> StreamingResponse:
    return StreamingResponse(
        stream_chat(
            conversation_id=req.conversation_id,
            message=req.message,
            generate_title=req.generate_title,
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
