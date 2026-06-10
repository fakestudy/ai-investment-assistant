import unittest
from datetime import UTC, datetime
import subprocess
import sys
from typing import Any

from model.base import Base
import model.agent_run  # noqa: F401
import model.agent_run_event  # noqa: F401
import model.approval  # noqa: F401


class RunModelMetadataTest(unittest.TestCase):
    def test_run_event_and_approval_tables_are_registered(self) -> None:
        expected = {
            "agent_runs",
            "agent_run_events",
            "approval_batches",
            "approval_requests",
        }

        self.assertTrue(expected.issubset(set(Base.metadata.tables)))

    def test_run_and_event_columns_exist(self) -> None:
        from model.agent_run import AgentRun
        from model.agent_run_event import AgentRunEvent

        self.assertIn("status", AgentRun.__table__.c)
        self.assertIn("cancel_requested_at", AgentRun.__table__.c)
        self.assertIn("assistant_message_id", AgentRun.__table__.c)

        for column_name in (
            "id",
            "run_id",
            "conversation_id",
            "message_id",
            "event_type",
            "payload",
            "created_at",
        ):
            self.assertIn(column_name, AgentRunEvent.__table__.c)

    def test_approval_columns_exist(self) -> None:
        from model.approval import ApprovalBatch, ApprovalRequest

        for column_name in (
            "id",
            "run_id",
            "message_id",
            "status",
            "expires_at",
            "resolved_at",
            "resolution_source",
            "created_at",
        ):
            self.assertIn(column_name, ApprovalBatch.__table__.c)

        for column_name in (
            "id",
            "approval_batch_id",
            "tool_invocation_id",
            "tool_name",
            "args",
            "decision",
            "decided_at",
            "created_at",
        ):
            self.assertIn(column_name, ApprovalRequest.__table__.c)

        foreign_keys = {
            fk.parent.name: fk.column.table.name
            for fk in ApprovalRequest.__table__.foreign_keys
        }
        self.assertEqual(foreign_keys, {"approval_batch_id": "approval_batches"})

    def test_approval_request_index_name_matches_migration(self) -> None:
        from model.approval import ApprovalRequest

        index_names = {index.name for index in ApprovalRequest.__table__.indexes}

        self.assertIn("ix_approval_requests_batch_id", index_names)
        self.assertNotIn("ix_approval_requests_approval_batch_id", index_names)

    def test_direct_model_imports_configure_mappers(self) -> None:
        snippets = [
            "import model.approval; from sqlalchemy.orm import configure_mappers; configure_mappers()",
            "import model.agent_run_event; from sqlalchemy.orm import configure_mappers; configure_mappers()",
        ]

        for snippet in snippets:
            with self.subTest(snippet=snippet):
                result = subprocess.run(
                    [sys.executable, "-c", snippet],
                    check=False,
                    capture_output=True,
                    text=True,
                )

                self.assertEqual(result.returncode, 0, result.stderr)


class _ScalarResult:
    def __init__(self, value: Any) -> None:
        self.value = value

    def scalar_one_or_none(self) -> Any:
        return self.value


class _ApprovalSession:
    def __init__(self, batch: Any) -> None:
        self.batch = batch
        self.flushes = 0
        self.statement: Any | None = None

    async def execute(self, statement: Any) -> _ScalarResult:
        self.statement = statement
        return _ScalarResult(self.batch)

    async def flush(self) -> None:
        self.flushes += 1


class _RunQuerySession:
    def __init__(self, run: Any) -> None:
        self.run = run
        self.statement: Any | None = None
        self.flushes = 0

    async def execute(self, statement: Any) -> _ScalarResult:
        from model.agent_run import ACTIVE_RUN_STATUSES

        self.statement = statement
        sql = str(statement)
        if "agent_runs.status IN" in sql and self.run.status not in ACTIVE_RUN_STATUSES:
            return _ScalarResult(None)
        return _ScalarResult(self.run)

    async def flush(self) -> None:
        self.flushes += 1


class _RunEventSession:
    def __init__(self, run: Any) -> None:
        self.run = run
        self.added: list[Any] = []
        self.flushes = 0

    def add(self, row: Any) -> None:
        self.added.append(row)

    async def get(self, model: Any, object_id: str) -> Any:
        from model.agent_run import AgentRun

        if model is AgentRun and object_id == self.run.id:
            return self.run
        return None

    async def flush(self) -> None:
        self.flushes += 1


class RunRepositoryBehaviorTest(unittest.IsolatedAsyncioTestCase):
    async def test_resolve_approval_batch_requires_complete_valid_decisions(
        self,
    ) -> None:
        from model.approval import ApprovalBatch, ApprovalRequest
        from repository.approval import resolve_approval_batch

        now = datetime(2026, 6, 9, 10, 0, tzinfo=UTC)
        batch = ApprovalBatch(
            id="batch-1",
            run_id="run-1",
            message_id="message-1",
            status="pending",
            expires_at=now,
            created_at=now,
        )
        batch.requests = [
            ApprovalRequest(
                id="request-1",
                approval_batch_id="batch-1",
                tool_invocation_id="tool-1",
                tool_name="Read",
                args={},
                decision="pending",
                created_at=now,
            ),
            ApprovalRequest(
                id="request-2",
                approval_batch_id="batch-1",
                tool_invocation_id="tool-2",
                tool_name="WebFetch",
                args={},
                decision="pending",
                created_at=now,
            ),
        ]
        session = _ApprovalSession(batch)

        with self.assertRaises(ValueError):
            await resolve_approval_batch(
                session,
                batch_id="batch-1",
                decisions={"request-1": "approve"},
            )

        self.assertEqual(batch.status, "pending")
        self.assertIsNone(batch.resolved_at)
        self.assertEqual([request.decision for request in batch.requests], ["pending", "pending"])
        self.assertEqual(session.flushes, 0)

    async def test_resolve_approval_batch_maps_valid_decisions(self) -> None:
        from model.approval import ApprovalBatch, ApprovalRequest
        from repository.approval import resolve_approval_batch

        now = datetime(2026, 6, 9, 10, 0, tzinfo=UTC)
        batch = ApprovalBatch(
            id="batch-1",
            run_id="run-1",
            message_id="message-1",
            status="pending",
            expires_at=now,
            created_at=now,
        )
        batch.requests = [
            ApprovalRequest(
                id="request-1",
                approval_batch_id="batch-1",
                tool_invocation_id="tool-1",
                tool_name="Read",
                args={},
                decision="pending",
                created_at=now,
            ),
            ApprovalRequest(
                id="request-2",
                approval_batch_id="batch-1",
                tool_invocation_id="tool-2",
                tool_name="WebFetch",
                args={},
                decision="pending",
                created_at=now,
            ),
        ]
        session = _ApprovalSession(batch)

        result = await resolve_approval_batch(
            session,
            batch_id="batch-1",
            decisions={"request-1": "approve", "request-2": "reject"},
        )

        self.assertIs(result, batch)
        self.assertEqual(batch.status, "resolved")
        self.assertEqual(batch.resolution_source, "manual")
        self.assertEqual([request.decision for request in batch.requests], ["approved", "rejected"])
        self.assertTrue(all(request.decided_at is not None for request in batch.requests))
        self.assertEqual(session.flushes, 1)

    async def test_resolve_approval_batch_locks_batch_row(self) -> None:
        from sqlalchemy.dialects import postgresql

        from model.approval import ApprovalBatch, ApprovalRequest
        from repository.approval import resolve_approval_batch

        now = datetime(2026, 6, 9, 10, 0, tzinfo=UTC)
        batch = ApprovalBatch(
            id="batch-1",
            run_id="run-1",
            message_id="message-1",
            status="pending",
            expires_at=now,
            created_at=now,
        )
        batch.requests = [
            ApprovalRequest(
                id="request-1",
                approval_batch_id="batch-1",
                tool_invocation_id="tool-1",
                tool_name="Read",
                args={},
                decision="pending",
                created_at=now,
            ),
        ]
        session = _ApprovalSession(batch)

        await resolve_approval_batch(
            session,
            batch_id="batch-1",
            decisions={"request-1": "approve"},
        )

        self.assertIsNotNone(session.statement)
        sql = str(session.statement.compile(dialect=postgresql.dialect()))
        self.assertIn("FOR UPDATE", sql)

    async def test_resolve_approval_batch_rejects_non_pending_batch(self) -> None:
        from model.approval import ApprovalBatch, ApprovalRequest
        from repository.approval import resolve_approval_batch

        now = datetime(2026, 6, 9, 10, 0, tzinfo=UTC)
        original_resolved_at = datetime(2026, 6, 9, 10, 1, tzinfo=UTC)
        batch = ApprovalBatch(
            id="batch-1",
            run_id="run-1",
            message_id="message-1",
            status="resolved",
            expires_at=now,
            resolved_at=original_resolved_at,
            resolution_source="manual",
            created_at=now,
        )
        batch.requests = [
            ApprovalRequest(
                id="request-1",
                approval_batch_id="batch-1",
                tool_invocation_id="tool-1",
                tool_name="Read",
                args={},
                decision="approved",
                decided_at=original_resolved_at,
                created_at=now,
            ),
        ]
        session = _ApprovalSession(batch)

        with self.assertRaises(ValueError):
            await resolve_approval_batch(
                session,
                batch_id="batch-1",
                decisions={"request-1": "reject"},
            )

        self.assertEqual(batch.status, "resolved")
        self.assertEqual(batch.resolved_at, original_resolved_at)
        self.assertEqual(batch.requests[0].decision, "approved")
        self.assertEqual(batch.requests[0].decided_at, original_resolved_at)
        self.assertEqual(session.flushes, 0)

    async def test_request_cancel_ignores_terminal_runs(self) -> None:
        from sqlalchemy.dialects import postgresql

        from model.agent_run import AgentRun
        from repository.agent_run import request_cancel

        now = datetime(2026, 6, 9, 10, 0, tzinfo=UTC)
        run = AgentRun(
            id="run-1",
            conversation_id="conversation-1",
            assistant_message_id="assistant-1",
            status="completed",
            created_at=now,
            updated_at=now,
            completed_at=now,
        )
        session = _RunQuerySession(run)

        result = await request_cancel(session, assistant_message_id="assistant-1")

        self.assertIsNone(result)
        self.assertIsNone(run.cancel_requested_at)
        self.assertEqual(session.flushes, 0)
        self.assertIn("agent_runs.status IN", str(session.statement))
        sql = str(session.statement.compile(dialect=postgresql.dialect()))
        self.assertIn("FOR UPDATE", sql)

    async def test_append_run_event_updates_run_last_event_id(self) -> None:
        from model.agent_run import AgentRun
        from model.agent_run_event import AgentRunEvent
        from repository.agent_run_event import append_run_event

        now = datetime(2026, 6, 9, 10, 0, tzinfo=UTC)
        run = AgentRun(
            id="run-1",
            conversation_id="conversation-1",
            assistant_message_id="assistant-1",
            status="running",
            created_at=now,
            updated_at=now,
        )
        event = AgentRunEvent(
            id=13,
            run_id="run-1",
            conversation_id="conversation-1",
            message_id="assistant-1",
            event_type="delta",
            payload={"type": "delta", "text": "hello"},
            created_at=now,
        )
        session = _RunEventSession(run)

        result = await append_run_event(session, event=event)

        self.assertIs(result, event)
        self.assertEqual(session.added, [event])
        self.assertEqual(run.last_event_id, 13)
        self.assertGreater(run.updated_at, now)
        self.assertEqual(session.flushes, 2)


if __name__ == "__main__":
    unittest.main()
