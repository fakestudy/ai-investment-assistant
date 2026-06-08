from fastapi.responses import StreamingResponse

from schema.chat import StreamChatRequest
from service.chat import stream_chat


async def run_stream_chat(req: StreamChatRequest) -> StreamingResponse:
    return StreamingResponse(
        stream_chat(
            conversation_id=req.conversation_id,
            message=req.message,
        ),
        media_type="text/event-stream",
    )
