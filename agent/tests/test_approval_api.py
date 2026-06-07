import asyncio
import inspect
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from controller.chat import submit_approval_decisions_stream
from schema.chat import ApprovalDecisionRequest
from service.approval import ApprovalDecisionConflict, ApprovalDecisionValidationError


class FakeManagedSession:
    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False
        self.exited = False

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


class FakeSessionContext:
    def __init__(self, session: FakeManagedSession) -> None:
        self.session = session

    async def __aenter__(self) -> FakeManagedSession:
        return self.session

    async def __aexit__(self, *_: object) -> None:
        self.session.exited = True


class ApprovalApiTest(unittest.TestCase):
    def test_approval_post_commits_before_streaming_from_request_cursor(self) -> None:
        asyncio.run(
            self._test_approval_post_commits_before_streaming_from_request_cursor()
        )

    def test_approval_post_maps_validation_to_422_and_conflict_to_409(self) -> None:
        asyncio.run(
            self._test_approval_post_maps_validation_to_422_and_conflict_to_409()
        )

    def test_app_registers_approval_decisions_route(self) -> None:
        from main import create_app

        paths = {route.path for route in create_app().routes}

        self.assertIn("/api/chat/approval/decisions/{batch_id}", paths)

    async def _test_approval_post_commits_before_streaming_from_request_cursor(
        self,
    ) -> None:
        self.assertEqual(
            list(inspect.signature(submit_approval_decisions_stream).parameters),
            ["batch_id", "req"],
        )
        session = FakeManagedSession()
        request = ApprovalDecisionRequest.model_validate(
            {
                "afterEventId": 8,
                "decisions": [
                    {"approvalRequestId": "approval-request-1", "decision": "approve"}
                ],
            }
        )
        result = SimpleNamespace(run=SimpleNamespace(id="run-approval-api"))

        async def fake_stream(
            run_id: str,
            *,
            after_event_id: int,
            wait_for_new_events: bool,
        ):
            self.assertTrue(session.committed)
            self.assertTrue(session.exited)
            self.assertEqual(run_id, "run-approval-api")
            self.assertEqual(after_event_id, 8)
            self.assertTrue(wait_for_new_events)
            yield 'id: 9\ndata: {"type":"approval_resolved","runId":"run-approval-api"}\n\n'

        with (
            patch(
                "controller.chat.AsyncSessionLocal",
                return_value=FakeSessionContext(session),
            ),
            patch(
                "controller.chat.submit_approval_decisions",
                new=AsyncMock(return_value=result),
            ),
            patch("controller.chat.stream_run_events", new=fake_stream),
        ):
            response = await submit_approval_decisions_stream("batch-1", request)
            chunks: list[str] = []
            async for chunk in response.body_iterator:
                chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)

        self.assertFalse(session.rolled_back)
        self.assertEqual(
            "".join(chunks),
            'id: 9\ndata: {"type":"approval_resolved","runId":"run-approval-api"}\n\n',
        )

    async def _test_approval_post_maps_validation_to_422_and_conflict_to_409(
        self,
    ) -> None:
        request = ApprovalDecisionRequest.model_validate(
            {
                "afterEventId": 1,
                "decisions": [
                    {"approvalRequestId": "approval-request-1", "decision": "approve"}
                ],
            }
        )

        for exc, expected_status in [
            (ApprovalDecisionValidationError("invalid"), 422),
            (ApprovalDecisionConflict("conflict"), 409),
        ]:
            session = FakeManagedSession()
            with (
                patch(
                    "controller.chat.AsyncSessionLocal",
                    return_value=FakeSessionContext(session),
                ),
                patch(
                    "controller.chat.submit_approval_decisions",
                    new=AsyncMock(side_effect=exc),
                ),
            ):
                with self.assertRaises(HTTPException) as caught:
                    await submit_approval_decisions_stream("batch-1", request)

            self.assertEqual(caught.exception.status_code, expected_status)
            self.assertFalse(session.committed)
            self.assertTrue(session.rolled_back)


if __name__ == "__main__":
    unittest.main()
