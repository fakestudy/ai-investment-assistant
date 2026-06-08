from fastapi import FastAPI

from controller.chat import run_stream_chat


app = FastAPI(title="Claude Agent Compatible Backend")

app.add_api_route(
    "/chat/stream",
    run_stream_chat,
    methods=["POST"],
    response_model=None,
)
