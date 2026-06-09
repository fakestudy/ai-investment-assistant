from fastapi.responses import JSONResponse, StreamingResponse

from core.database import AsyncSessionLocal
from schema.chat import ConversationMessagesResponse, StreamChatRequest
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
