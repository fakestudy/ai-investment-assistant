from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db_session
from schema.chat_conversations import (
    ChatConversation,
    DeleteConversationRequest,
    DeleteConversationResponse,
    UpdateConversationTitleRequest,
)
from service.chat_conversations import (
    create_chat_conversation,
    delete_chat_conversation,
    get_conversations_list as get_list,
    get_conversation_messages as get_messages,
    update_chat_conversation_title,
)


async def create_conversation(
    session: AsyncSession = Depends(get_db_session),
) -> ChatConversation:
    return await create_chat_conversation(session)


async def get_conversations_list(session: AsyncSession = Depends(get_db_session)):
    return await get_list(session)


async def get_conversation_messages(
    session: AsyncSession = Depends(get_db_session), *, conversation_id: str
):
    return await get_messages(session=session, conversation_id=conversation_id)


async def update_conversation_title(
    req: UpdateConversationTitleRequest,
    session: AsyncSession = Depends(get_db_session),
) -> ChatConversation:
    conversation = await update_chat_conversation_title(
        session=session,
        conversation_id=req.conversation_id,
        title=req.title,
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    return conversation


async def delete_conversation(
    req: DeleteConversationRequest,
    session: AsyncSession = Depends(get_db_session),
) -> DeleteConversationResponse:
    deleted = await delete_chat_conversation(
        session=session,
        conversation_id=req.conversation_id,
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation not found")

    return DeleteConversationResponse(
        conversation_id=req.conversation_id,
        deleted=True,
    )
