from inspect import isawaitable

import uvicorn
from fastapi import FastAPI, Response
from fastapi.responses import StreamingResponse

from controller import chat as chat_controller
from schema.chat import (
    ApprovalDecisionsRequest,
    ChatStreamResumeRequest,
    EditMessageRequest,
)


app = FastAPI(title="Claude Agent Compatible Backend")


def health() -> dict[str, str]:
    return {"status": "ok"}


async def _resume_chat_stream_route(req: ChatStreamResumeRequest):
    result = chat_controller.resume_chat_stream(req)
    if isawaitable(result):
        result = await result
    if isinstance(result, Response):
        return result
    return StreamingResponse(result, media_type="text/event-stream")


async def _approval_decisions_route(
    batch_id: str,
    req: ApprovalDecisionsRequest,
):
    result = chat_controller.submit_approval_decisions(batch_id, req)
    if isawaitable(result):
        result = await result
    if isinstance(result, Response):
        return result
    return StreamingResponse(result, media_type="text/event-stream")


async def _edit_message_route(message_id: str, req: EditMessageRequest):
    result = chat_controller.edit_message(message_id, req.content)
    if isawaitable(result):
        return await result
    return result


async def _cancel_chat_stream_route(message_id: str):
    result = chat_controller.cancel_chat_stream(message_id)
    if isawaitable(result):
        result = await result
    if isinstance(result, Response):
        return result
    return Response(status_code=204)


app.add_api_route("/api/health", health, methods=["GET"])

app.add_api_route(
    "/api/conversations",
    chat_controller.create_conversation,
    methods=["POST"],
    response_model=None,
)
app.add_api_route(
    "/api/conversations/list",
    chat_controller.get_conversations_list,
    methods=["GET"],
    response_model=None,
)
app.add_api_route(
    "/api/conversation/messages/{conversation_id}",
    chat_controller.get_conversation_messages,
    methods=["GET"],
    response_model=None,
)
app.add_api_route(
    "/api/conversation/title/update",
    chat_controller.update_conversation_title,
    methods=["POST"],
    response_model=None,
)
app.add_api_route(
    "/api/conversation/delete",
    chat_controller.delete_conversation,
    methods=["POST"],
    response_model=None,
)
app.add_api_route(
    "/api/chat/stream",
    chat_controller.run_stream_chat,
    methods=["POST"],
    response_model=None,
)
app.add_api_route(
    "/api/chat/stream/resume",
    _resume_chat_stream_route,
    methods=["POST"],
    response_model=None,
)
app.add_api_route(
    "/api/chat/approval/decisions/{batch_id}",
    _approval_decisions_route,
    methods=["POST"],
    response_model=None,
)
app.add_api_route(
    "/api/messages/{message_id}",
    _edit_message_route,
    methods=["PATCH"],
    response_model=None,
)
app.add_api_route(
    "/api/chat/streams/{message_id}/cancel",
    _cancel_chat_stream_route,
    methods=["POST"],
    response_model=None,
)
app.add_api_route(
    "/chat/stream",
    chat_controller.run_stream_chat,
    methods=["POST"],
    response_model=None,
)


def main() -> None:
    uvicorn.run("main:app", host="127.0.0.1", port=8081, reload=True)


if __name__ == "__main__":
    main()
