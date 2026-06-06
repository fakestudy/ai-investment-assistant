import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from controller.chat import run_stream_chat
from schema.chat import ChatStreamRequest
from service.chat_run import ConversationRunConflict


class FakeSession:
    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


class ChatControllerTest(unittest.TestCase):
    def test_stream_chat_commits_before_streaming_run_events(self) -> None:
        asyncio.run(self._test_stream_chat_commits_before_streaming_run_events())

    def test_stream_chat_maps_active_run_conflict_to_409(self) -> None:
        asyncio.run(self._test_stream_chat_maps_active_run_conflict_to_409())

    async def _test_stream_chat_commits_before_streaming_run_events(self) -> None:
        session = FakeSession()
        request = ChatStreamRequest.model_validate(
            {"conversationId": "conversation-controller", "message": "你好"}
        )
        creation = SimpleNamespace(run=SimpleNamespace(id="run-controller"))

        async def fake_stream(run_id: str, *, after_event_id: int):
            self.assertTrue(session.committed)
            self.assertEqual(run_id, "run-controller")
            self.assertEqual(after_event_id, 0)
            yield 'id: 1\ndata: {"type":"run_created","runId":"run-controller"}\n\n'

        with (
            patch("controller.chat.create_chat_run", new=AsyncMock(return_value=creation)),
            patch("controller.chat.stream_run_events", new=fake_stream),
        ):
            response = await run_stream_chat(request, session)
            chunks: list[str] = []
            async for chunk in response.body_iterator:
                chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)

        self.assertFalse(session.rolled_back)
        self.assertEqual(
            "".join(chunks),
            'id: 1\ndata: {"type":"run_created","runId":"run-controller"}\n\n',
        )

    async def _test_stream_chat_maps_active_run_conflict_to_409(self) -> None:
        session = FakeSession()
        request = ChatStreamRequest.model_validate(
            {"conversationId": "conversation-controller", "message": "你好"}
        )

        with patch(
            "controller.chat.create_chat_run",
            new=AsyncMock(side_effect=ConversationRunConflict("conversation-controller")),
        ):
            with self.assertRaises(HTTPException) as caught:
                await run_stream_chat(request, session)

        self.assertEqual(caught.exception.status_code, 409)
        self.assertFalse(session.committed)
        self.assertTrue(session.rolled_back)


if __name__ == "__main__":
    unittest.main()
