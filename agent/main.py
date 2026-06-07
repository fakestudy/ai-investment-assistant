from dotenv import load_dotenv
from fastapi import FastAPI, APIRouter
import uvicorn
from pathlib import Path
from controller.chat import (
    resume_stream_chat,
    run_stream_chat,
    submit_approval_decisions_stream,
)
from controller.chat_conversations import (
    create_conversation,
    delete_conversation,
    get_conversations_list,
    get_conversation_messages,
    update_conversation_title,
)
from schema.chat_conversations import ChatConversation

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def health() -> dict[str, str]:
    return {"status": "ok"}


def create_app() -> FastAPI:

    app = FastAPI()
    api_router = APIRouter(prefix="/api")

    api_router.get("/health")(health)

    # conversations
    api_router.post("/conversations", response_model=ChatConversation)(
        create_conversation
    )
    api_router.get("/conversations/list")(get_conversations_list)
    api_router.add_api_route(
        "/conversation/messages/{conversation_id}",
        get_conversation_messages,
        methods=["GET"],
    )
    api_router.add_api_route(
        "/conversation/title/update",
        update_conversation_title,
        methods=["POST"],
    )
    api_router.add_api_route(
        "/conversation/delete",
        delete_conversation,
        methods=["POST"],
    )

    # chat
    api_router.post("/chat/stream")(run_stream_chat)
    api_router.post("/chat/stream/resume")(resume_stream_chat)
    api_router.post("/chat/approval/decisions/{batch_id}")(
        submit_approval_decisions_stream
    )

    app.include_router(api_router)
    return app


def main() -> None:
    uvicorn.run("main:create_app", host="127.0.0.1", port=8081, reload=True)


if __name__ == "__main__":
    main()
