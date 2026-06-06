import asyncio
import inspect
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from controller.chat import resume_stream_chat, run_stream_chat
from schema.chat import ChatStreamRequest, ChatStreamResumeRequest
from service.chat_run import ConversationRunConflict


class FakeSession:
    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


class FakeManagedSession(FakeSession):
    def __init__(self) -> None:
        super().__init__()
        self.exited = False

    async def get(self, _model: object, run_id: str) -> object:
        return SimpleNamespace(id=run_id)


class FakeSessionContext:
    def __init__(self, session: FakeManagedSession) -> None:
        self.session = session

    async def __aenter__(self) -> FakeManagedSession:
        return self.session

    async def __aexit__(self, *_: object) -> None:
        self.session.exited = True


class ChatControllerTest(unittest.TestCase):
    def test_stream_chat_commits_before_streaming_run_events(self) -> None:
        asyncio.run(self._test_stream_chat_commits_before_streaming_run_events())

    def test_stream_chat_maps_active_run_conflict_to_409(self) -> None:
        asyncio.run(self._test_stream_chat_maps_active_run_conflict_to_409())

    def test_stream_chat_closes_create_session_before_streaming(self) -> None:
        asyncio.run(self._test_stream_chat_closes_create_session_before_streaming())

    def test_resume_stream_chat_closes_lookup_session_before_streaming(self) -> None:
        asyncio.run(
            self._test_resume_stream_chat_closes_lookup_session_before_streaming()
        )

    async def _test_stream_chat_commits_before_streaming_run_events(self) -> None:
        session = FakeManagedSession()
        request = ChatStreamRequest.model_validate(
            {"conversationId": "conversation-controller", "message": "你好"}
        )
        creation = SimpleNamespace(run=SimpleNamespace(id="run-controller"))

        async def fake_stream(
            run_id: str,
            *,
            after_event_id: int,
            wait_for_new_events: bool,
        ):
            self.assertTrue(session.committed)
            self.assertEqual(run_id, "run-controller")
            self.assertEqual(after_event_id, 0)
            self.assertTrue(wait_for_new_events)
            yield 'id: 1\ndata: {"type":"run_created","runId":"run-controller"}\n\n'

        with (
            patch(
                "controller.chat.AsyncSessionLocal",
                return_value=FakeSessionContext(session),
            ),
            patch("controller.chat.create_chat_run", new=AsyncMock(return_value=creation)),
            patch("controller.chat.stream_run_events", new=fake_stream),
        ):
            response = await run_stream_chat(request)
            chunks: list[str] = []
            async for chunk in response.body_iterator:
                chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)

        self.assertFalse(session.rolled_back)
        self.assertEqual(
            "".join(chunks),
            'id: 1\ndata: {"type":"run_created","runId":"run-controller"}\n\n',
        )

    async def _test_stream_chat_closes_create_session_before_streaming(self) -> None:
        self.assertEqual(list(inspect.signature(run_stream_chat).parameters), ["req"])
        create_session = FakeManagedSession()
        request = ChatStreamRequest.model_validate(
            {"conversationId": "conversation-controller", "message": "你好"}
        )
        creation = SimpleNamespace(run=SimpleNamespace(id="run-controller"))

        async def fake_stream(
            run_id: str,
            *,
            after_event_id: int,
            wait_for_new_events: bool,
        ):
            self.assertTrue(create_session.committed)
            self.assertTrue(create_session.exited)
            self.assertEqual(run_id, "run-controller")
            self.assertEqual(after_event_id, 0)
            self.assertTrue(wait_for_new_events)
            yield 'id: 1\ndata: {"type":"run_created","runId":"run-controller"}\n\n'

        with (
            patch(
                "controller.chat.AsyncSessionLocal",
                return_value=FakeSessionContext(create_session),
            ),
            patch("controller.chat.create_chat_run", new=AsyncMock(return_value=creation)),
            patch("controller.chat.stream_run_events", new=fake_stream),
        ):
            response = await run_stream_chat(request)
            chunks: list[str] = []
            async for chunk in response.body_iterator:
                chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)

        self.assertFalse(create_session.rolled_back)
        self.assertEqual(
            "".join(chunks),
            'id: 1\ndata: {"type":"run_created","runId":"run-controller"}\n\n',
        )

    async def _test_stream_chat_maps_active_run_conflict_to_409(self) -> None:
        session = FakeManagedSession()
        request = ChatStreamRequest.model_validate(
            {"conversationId": "conversation-controller", "message": "你好"}
        )

        with (
            patch(
                "controller.chat.AsyncSessionLocal",
                return_value=FakeSessionContext(session),
            ),
            patch(
                "controller.chat.create_chat_run",
                new=AsyncMock(
                    side_effect=ConversationRunConflict("conversation-controller")
                ),
            ),
        ):
            with self.assertRaises(HTTPException) as caught:
                await run_stream_chat(request)

        self.assertEqual(caught.exception.status_code, 409)
        self.assertFalse(session.committed)
        self.assertTrue(session.rolled_back)

    async def _test_resume_stream_chat_closes_lookup_session_before_streaming(
        self,
    ) -> None:
        self.assertEqual(list(inspect.signature(resume_stream_chat).parameters), ["req"])
        lookup_session = FakeManagedSession()
        request = ChatStreamResumeRequest.model_validate(
            {"runId": "run-resume-controller", "afterEventId": 7}
        )

        async def fake_stream(
            run_id: str,
            *,
            after_event_id: int,
            wait_for_new_events: bool,
        ):
            self.assertTrue(lookup_session.exited)
            self.assertEqual(run_id, "run-resume-controller")
            self.assertEqual(after_event_id, 7)
            self.assertTrue(wait_for_new_events)
            yield 'id: 8\ndata: {"type":"done","runId":"run-resume-controller"}\n\n'

        with (
            patch(
                "controller.chat.AsyncSessionLocal",
                return_value=FakeSessionContext(lookup_session),
                create=True,
            ),
            patch("controller.chat.stream_run_events", new=fake_stream),
        ):
            response = await resume_stream_chat(request)
            chunks: list[str] = []
            async for chunk in response.body_iterator:
                chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)

        self.assertEqual(
            "".join(chunks),
            'id: 8\ndata: {"type":"done","runId":"run-resume-controller"}\n\n',
        )


if __name__ == "__main__":
    unittest.main()
