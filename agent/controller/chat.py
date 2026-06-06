from fastapi.responses import StreamingResponse

from schema.chat import ChatStreamRequest
from service.chat import iter_sse_events


async def run_stream_chat(
    req: ChatStreamRequest,
):
    return StreamingResponse(
        iter_sse_events(req),
        media_type="text/event-stream",
    )
