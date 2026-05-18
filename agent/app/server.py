from collections.abc import AsyncIterator
import asyncio

import grpc

from app.config import load_settings
from app.graphs.question_answer import QuestionAnswerGraph, QuestionInput
from app.providers.deepseek import DeepSeekError, DeepSeekProvider
from investment.v1 import agent_pb2, agent_pb2_grpc


def _page_context_to_dict(page_context: agent_pb2.PageContext) -> dict[str, str]:
    return {
        "route": page_context.route,
        "symbol": page_context.symbol,
        "event_id": page_context.event_id,
        "research_card_id": page_context.research_card_id,
    }


class AgentServicer(agent_pb2_grpc.AgentServiceServicer):
    def __init__(self, graph: QuestionAnswerGraph) -> None:
        self.graph = graph

    async def StreamAnswerQuestion(
        self,
        request: agent_pb2.StreamAnswerQuestionRequest,
        context: grpc.aio.ServicerContext | None,
    ) -> AsyncIterator[agent_pb2.AnswerChunk]:
        yield agent_pb2.AnswerChunk(
            conversation_id=request.conversation_id,
            assistant_message_id=request.assistant_message_id,
            type=agent_pb2.ANSWER_CHUNK_TYPE_METADATA,
        )

        graph_input = QuestionInput(
            user_id=request.user_id,
            conversation_id=request.conversation_id,
            user_message_id=request.user_message_id,
            assistant_message_id=request.assistant_message_id,
            content=request.content,
            page_context=_page_context_to_dict(request.page_context),
        )

        try:
            async for content in self.graph.stream(graph_input):
                yield agent_pb2.AnswerChunk(
                    conversation_id=request.conversation_id,
                    assistant_message_id=request.assistant_message_id,
                    type=agent_pb2.ANSWER_CHUNK_TYPE_DELTA,
                    content=content,
                )
            yield agent_pb2.AnswerChunk(
                conversation_id=request.conversation_id,
                assistant_message_id=request.assistant_message_id,
                type=agent_pb2.ANSWER_CHUNK_TYPE_DONE,
                finish_reason="stop",
            )
        except DeepSeekError as exc:
            yield agent_pb2.AnswerChunk(
                conversation_id=request.conversation_id,
                assistant_message_id=request.assistant_message_id,
                type=agent_pb2.ANSWER_CHUNK_TYPE_ERROR,
                error_code=exc.code,
                error_message=str(exc),
            )
        except ValueError as exc:
            yield agent_pb2.AnswerChunk(
                conversation_id=request.conversation_id,
                assistant_message_id=request.assistant_message_id,
                type=agent_pb2.ANSWER_CHUNK_TYPE_ERROR,
                error_code="INVALID_ARGUMENT",
                error_message=str(exc),
            )


async def serve() -> None:
    settings = load_settings()
    provider = DeepSeekProvider(
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        model=settings.deepseek_model,
        timeout_seconds=settings.deepseek_timeout_seconds,
    )
    graph = QuestionAnswerGraph(provider=provider)
    server = grpc.aio.server()
    agent_pb2_grpc.add_AgentServiceServicer_to_server(AgentServicer(graph=graph), server)
    server.add_insecure_port(settings.grpc_bind_addr)
    await server.start()
    await server.wait_for_termination()


if __name__ == "__main__":
    asyncio.run(serve())
