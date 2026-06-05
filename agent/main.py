from dotenv import load_dotenv
from fastapi import FastAPI
import uvicorn
from pathlib import Path
from controller.chat import run_stream_chat
from controller.chat_conversations import create_conversation
from schema.chat_conversations import ChatConversation

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def health() -> dict[str, str]:
    return {"status": "ok"}


def create_app() -> FastAPI:
    app = FastAPI()
    app.get("/api/health")(health)
    app.post("/api/conversations", response_model=ChatConversation)(create_conversation)
    app.post("/api/chat/stream")(run_stream_chat)
    return app


def main() -> None:

    uvicorn.run("main:create_app", host="127.0.0.1", port=8081, reload=True)


if __name__ == "__main__":
    main()
