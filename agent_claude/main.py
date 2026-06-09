from fastapi import FastAPI

from controller.chat import (
    create_conversation,
    delete_conversation,
    get_conversation_messages,
    get_conversations_list,
    run_stream_chat,
    unsupported_approval_decisions,
    unsupported_stream_resume,
    update_conversation_title,
)


app = FastAPI(title="Claude Agent Compatible Backend")

app.add_api_route(
    "/api/conversations",
    create_conversation,
    methods=["POST"],
    response_model=None,
)
app.add_api_route(
    "/api/conversations/list",
    get_conversations_list,
    methods=["GET"],
    response_model=None,
)
app.add_api_route(
    "/api/conversation/messages/{conversation_id}",
    get_conversation_messages,
    methods=["GET"],
    response_model=None,
)
app.add_api_route(
    "/api/conversation/title/update",
    update_conversation_title,
    methods=["POST"],
    response_model=None,
)
app.add_api_route(
    "/api/conversation/delete",
    delete_conversation,
    methods=["POST"],
    response_model=None,
)
app.add_api_route(
    "/api/chat/stream",
    run_stream_chat,
    methods=["POST"],
    response_model=None,
)
app.add_api_route(
    "/api/chat/stream/resume",
    unsupported_stream_resume,
    methods=["POST"],
    response_model=None,
)
app.add_api_route(
    "/api/chat/approval/decisions/{batch_id}",
    unsupported_approval_decisions,
    methods=["POST"],
    response_model=None,
)
app.add_api_route(
    "/chat/stream",
    run_stream_chat,
    methods=["POST"],
    response_model=None,
)
