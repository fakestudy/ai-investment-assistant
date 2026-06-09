from fastapi import FastAPI

from controller.chat import get_conversation_messages, run_stream_chat


app = FastAPI(title="Claude Agent Compatible Backend")

app.add_api_route(
    "/api/conversation/messages/{conversation_id}",
    get_conversation_messages,
    methods=["GET"],
    response_model=None,
)
app.add_api_route(
    "/api/chat/stream",
    run_stream_chat,
    methods=["POST"],
    response_model=None,
)
app.add_api_route(
    "/chat/stream",
    run_stream_chat,
    methods=["POST"],
    response_model=None,
)
