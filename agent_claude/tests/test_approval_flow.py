import asyncio
import json
import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny
from claude_agent_sdk.types import ToolPermissionContext
from fastapi.testclient import TestClient


def request_payload(req):
    if hasattr(req, "model_dump"):
        return req.model_dump(by_alias=True)
    if isinstance(req, dict):
        return req
    return vars(req)


class ApprovalFlowApiTest(unittest.TestCase):
    def test_approval_decisions_returns_sse_when_service_is_patched(self) -> None:
        from main import app

        captured_calls = []

        async def fake_submit_approval_decisions(batch_id: str, req):
            captured_calls.append((batch_id, req))
            yield (
                'id: 44\ndata: {"type":"done","runId":"run-1",'
                '"messageId":"assistant-1"}\n\n'
            )

        with patch(
            "controller.chat.submit_approval_decisions",
            fake_submit_approval_decisions,
            create=True,
        ):
            response = TestClient(app).post(
                "/api/chat/approval/decisions/batch-1",
                json={
                    "decisions": [
                        {
                            "approvalRequestId": "request-1",
                            "decision": "approve",
                        }
                    ],
                    "afterEventId": 43,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/event-stream", response.headers["content-type"])
        batch_id, req = captured_calls[0]
        payload = request_payload(req)
        self.assertEqual(batch_id, "batch-1")
        self.assertEqual(
            payload["decisions"],
            [{"approvalRequestId": "request-1", "decision": "approve"}],
        )
        self.assertEqual(payload["afterEventId"], 43)
        self.assertIn("id: 44", response.text)

    def test_approval_decision_request_accepts_frontend_aliases(self) -> None:
        from schema.chat import ApprovalDecisionsRequest

        req = ApprovalDecisionsRequest.model_validate(
            {
                "decisions": [
                    {
                        "approvalRequestId": "request-1",
                        "decision": "reject",
                    }
                ],
                "afterEventId": 9,
            }
        )

        self.assertEqual(req.decisions[0].approval_request_id, "request-1")
        self.assertEqual(req.decisions[0].decision, "reject")
        self.assertEqual(req.after_event_id, 9)
        self.assertEqual(
            req.model_dump(by_alias=True),
            {
                "decisions": [
                    {
                        "approvalRequestId": "request-1",
                        "decision": "reject",
                    }
                ],
                "afterEventId": 9,
            },
        )


class ApprovalGateTest(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self) -> None:
        from service import approval_gate

        approval_gate.clear_approval_futures()

    async def test_non_required_tool_allows_immediately(self) -> None:
        from service.approval_gate import (
            RunApprovalContext,
            build_can_use_tool,
        )

        session = _ApprovalSession()
        hook = build_can_use_tool(
            RunApprovalContext(
                run_id="run-1",
                conversation_id="conversation-1",
                message_id="assistant-1",
                approval_required_tools=("WebFetch",),
                dependencies=_approval_dependencies(session),
            )
        )

        result = await hook(
            "Read",
            {"file_path": "README.md"},
            ToolPermissionContext(tool_use_id="tool-1"),
        )

        self.assertIsInstance(result, PermissionResultAllow)
        self.assertEqual(session.created_batches, [])
        self.assertEqual(session.operations, [])

    async def test_required_tool_creates_pending_batch_and_allows_after_decision(
        self,
    ) -> None:
        from schema.chat import ApprovalDecisionsRequest
        from service.approval_gate import (
            RunApprovalContext,
            build_can_use_tool,
            submit_approval_decisions,
        )

        session = _ApprovalSession()
        hook = build_can_use_tool(
            RunApprovalContext(
                run_id="run-1",
                conversation_id="conversation-1",
                message_id="assistant-1",
                approval_required_tools=("WebFetch",),
                dependencies=_approval_dependencies(session),
            )
        )

        pending = asyncio.create_task(
            hook(
                "WebFetch",
                {"url": "https://example.com"},
                ToolPermissionContext(tool_use_id="tool-1"),
            )
        )
        await _wait_for(lambda: session.statuses == ["awaiting_approval"])

        self.assertFalse(pending.done())
        self.assertEqual(len(session.created_batches), 1)
        created_batch = session.created_batches[0]
        self.assertEqual(created_batch.status, "pending")
        self.assertEqual(created_batch.requests[0].tool_invocation_id, "tool-1")
        self.assertEqual(created_batch.requests[0].decision, "pending")
        self.assertEqual(session.appended_events[0].event_type, "approval_required")
        self.assertEqual(
            session.appended_events[0].payload["part"]["batch"]["id"],
            created_batch.id,
        )

        frames = [
            frame
            async for frame in submit_approval_decisions(
                created_batch.id,
                ApprovalDecisionsRequest.model_validate(
                    {
                        "decisions": [
                            {
                                "approvalRequestId": created_batch.requests[0].id,
                                "decision": "approve",
                            }
                        ],
                        "afterEventId": 1,
                    }
                ),
                dependencies=_approval_dependencies(session),
            )
        ]
        result = await asyncio.wait_for(pending, timeout=1)

        self.assertIsInstance(result, PermissionResultAllow)
        self.assertEqual(result.updated_input, {"url": "https://example.com"})
        self.assertIn("resuming", session.statuses)
        self.assertEqual(session.appended_events[-1].event_type, "approval_resolved")
        self.assertIn('"approval_resolved"', "".join(frames))

    async def test_required_tool_denies_after_reject_decision(self) -> None:
        from schema.chat import ApprovalDecisionsRequest
        from service.approval_gate import (
            RunApprovalContext,
            build_can_use_tool,
            submit_approval_decisions,
        )

        session = _ApprovalSession()
        hook = build_can_use_tool(
            RunApprovalContext(
                run_id="run-1",
                conversation_id="conversation-1",
                message_id="assistant-1",
                approval_required_tools=("WebFetch",),
                dependencies=_approval_dependencies(session),
            )
        )

        pending = asyncio.create_task(
            hook(
                "WebFetch",
                {"url": "https://example.com"},
                ToolPermissionContext(tool_use_id="tool-2"),
            )
        )
        await _wait_for(lambda: bool(session.created_batches))
        created_batch = session.created_batches[0]

        _ = [
            frame
            async for frame in submit_approval_decisions(
                created_batch.id,
                ApprovalDecisionsRequest.model_validate(
                    {
                        "decisions": [
                            {
                                "approvalRequestId": created_batch.requests[0].id,
                                "decision": "reject",
                            }
                        ],
                        "afterEventId": 1,
                    }
                ),
                dependencies=_approval_dependencies(session),
            )
        ]
        result = await asyncio.wait_for(pending, timeout=1)

        self.assertIsInstance(result, PermissionResultDeny)
        self.assertEqual(result.message, "Tool execution rejected by user")
        self.assertFalse(result.interrupt)

    async def test_submit_approval_decisions_resolves_future_and_streams_events(
        self,
    ) -> None:
        from schema.chat import ApprovalDecisionsRequest
        from service import approval_gate
        from service.approval_gate import submit_approval_decisions

        session = _ApprovalSession()
        batch = session.seed_batch()
        future = asyncio.get_running_loop().create_future()
        approval_gate.register_approval_future(batch.id, future)

        frames = [
            frame
            async for frame in submit_approval_decisions(
                batch.id,
                ApprovalDecisionsRequest.model_validate(
                    {
                        "decisions": [
                            {
                                "approvalRequestId": batch.requests[0].id,
                                "decision": "approve",
                            }
                        ],
                        "afterEventId": 0,
                    }
                ),
                dependencies=_approval_dependencies(session),
            )
        ]

        self.assertEqual(future.result(), {"request-1": "approve"})
        self.assertEqual(session.resolved_decisions, {"request-1": "approve"})
        self.assertEqual(session.statuses, ["resuming"])
        self.assertEqual(session.appended_events[0].event_type, "approval_resolved")
        event_id, payload = _decode_sse(frames[0])
        self.assertEqual(event_id, 1)
        self.assertEqual(payload["type"], "approval_resolved")
        self.assertEqual(payload["batch"]["status"], "resolved")


def _decode_sse(frame: str):
    lines = frame.splitlines()
    event_id = int(
        next(line.removeprefix("id: ") for line in lines if line.startswith("id: "))
    )
    payload = json.loads(
        next(line.removeprefix("data: ") for line in lines if line.startswith("data: "))
    )
    return event_id, payload


async def _wait_for(predicate) -> None:
    for _ in range(50):
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition was not reached")


class _ApprovalSession:
    def __init__(self) -> None:
        self.created_batches = []
        self.batches = {}
        self.appended_events = []
        self.statuses = []
        self.operations = []
        self.commits = 0
        self.resolved_decisions = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def commit(self) -> None:
        self.commits += 1
        self.operations.append("commit")

    def seed_batch(self):
        from model.approval import ApprovalBatch, ApprovalRequest

        now = datetime(2026, 6, 9, 10, 0, tzinfo=UTC)
        batch = ApprovalBatch(
            id="batch-1",
            run_id="run-1",
            message_id="assistant-1",
            status="pending",
            expires_at=now + timedelta(minutes=30),
            created_at=now,
        )
        batch.requests = [
            ApprovalRequest(
                id="request-1",
                approval_batch_id="batch-1",
                tool_invocation_id="tool-1",
                tool_name="WebFetch",
                args={"url": "https://example.com"},
                decision="pending",
                created_at=now,
            )
        ]
        self.batches[batch.id] = batch
        return batch


class _ApprovalSessionFactory:
    def __init__(self, session: _ApprovalSession) -> None:
        self.session = session

    def __call__(self) -> _ApprovalSession:
        return self.session


def _approval_dependencies(session: _ApprovalSession):
    from service import run_events
    from service.approval_gate import ApprovalGateDependencies

    async def fake_create_approval_batch(db_session, *, batch, requests):
        db_session.created_batches.append(batch)
        batch.requests = list(requests)
        db_session.batches[batch.id] = batch
        db_session.operations.append("create_batch")
        return batch

    async def fake_resolve_approval_batch(db_session, *, batch_id, decisions):
        batch = db_session.batches[batch_id]
        db_session.resolved_decisions = dict(decisions)
        batch.status = "resolved"
        batch.resolved_at = datetime(2026, 6, 9, 10, 2, tzinfo=UTC)
        batch.resolution_source = "manual"
        for request in batch.requests:
            request.decision = "approved" if decisions[request.id] == "approve" else "rejected"
            request.decided_at = batch.resolved_at
        db_session.operations.append("resolve_batch")
        return batch

    async def fake_update_run_status(db_session, *, run_id, status, error=None):
        _ = (run_id, error)
        db_session.statuses.append(status)
        db_session.operations.append(f"status:{status}")
        return SimpleNamespace(id=run_id, status=status)

    async def fake_append_run_event_row(db_session, *, event):
        event.id = len(db_session.appended_events) + 1
        db_session.appended_events.append(event)
        db_session.operations.append(f"event:{event.event_type}")
        return event

    async def fake_stream_run_events(run_id, after_event_id):
        for event in session.appended_events:
            if event.run_id == run_id and int(event.id) > after_event_id:
                yield run_events.format_persisted_event(event)

    return ApprovalGateDependencies(
        async_session_factory=_ApprovalSessionFactory(session),
        create_approval_batch=fake_create_approval_batch,
        resolve_approval_batch=fake_resolve_approval_batch,
        update_run_status=fake_update_run_status,
        append_run_event_row=fake_append_run_event_row,
        stream_run_events=fake_stream_run_events,
        notify_run_event=lambda run_id, event_id: None,
        id_factory=_IdFactory(),
        now_factory=lambda: datetime(2026, 6, 9, 10, 0, tzinfo=UTC),
    )


class _IdFactory:
    def __init__(self) -> None:
        self.next_id = 0

    def __call__(self) -> str:
        self.next_id += 1
        return f"id-{self.next_id}"


if __name__ == "__main__":
    unittest.main()
