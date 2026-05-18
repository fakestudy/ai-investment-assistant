from collections.abc import AsyncIterator

import grpc
import pytest

from app.server import AgentServicer
from investment.v1 import agent_pb2, agent_pb2_grpc


class FakeGraph:
    async def stream(self, request) -> AsyncIterator[str]:
        yield "first "
        yield "second"


@pytest.mark.asyncio
async def test_stream_answer_question_returns_metadata_delta_done():
    servicer = AgentServicer(graph=FakeGraph())
    request = agent_pb2.StreamAnswerQuestionRequest(
        user_id="user-1",
        conversation_id="conversation-1",
        user_message_id="message-user-1",
        assistant_message_id="message-assistant-1",
        content="hello",
        page_context=agent_pb2.PageContext(route="/", symbol="AAPL"),
    )

    chunks = [chunk async for chunk in servicer.StreamAnswerQuestion(request, None)]

    assert [chunk.type for chunk in chunks] == [
        agent_pb2.ANSWER_CHUNK_TYPE_METADATA,
        agent_pb2.ANSWER_CHUNK_TYPE_DELTA,
        agent_pb2.ANSWER_CHUNK_TYPE_DELTA,
        agent_pb2.ANSWER_CHUNK_TYPE_DONE,
    ]
    assert chunks[1].content == "first "
    assert chunks[2].content == "second"


@pytest.mark.asyncio
async def test_grpc_server_streams_answer_chunks():
    server = grpc.aio.server()
    agent_pb2_grpc.add_AgentServiceServicer_to_server(
        AgentServicer(graph=FakeGraph()), server
    )
    try:
        port = server.add_insecure_port("127.0.0.1:0")
    except RuntimeError as exc:
        pytest.skip(f"gRPC port binding is unavailable in this environment: {exc}")
    await server.start()

    try:
        async with grpc.aio.insecure_channel(f"127.0.0.1:{port}") as channel:
            stub = agent_pb2_grpc.AgentServiceStub(channel)
            request = agent_pb2.StreamAnswerQuestionRequest(
                user_id="user-1",
                conversation_id="conversation-1",
                user_message_id="message-user-1",
                assistant_message_id="message-assistant-1",
                content="hello",
            )

            chunks = [chunk async for chunk in stub.StreamAnswerQuestion(request)]

        assert [chunk.type for chunk in chunks] == [
            agent_pb2.ANSWER_CHUNK_TYPE_METADATA,
            agent_pb2.ANSWER_CHUNK_TYPE_DELTA,
            agent_pb2.ANSWER_CHUNK_TYPE_DELTA,
            agent_pb2.ANSWER_CHUNK_TYPE_DONE,
        ]
        assert chunks[1].content == "first "
        assert chunks[2].content == "second"
    finally:
        await server.stop(grace=0)
