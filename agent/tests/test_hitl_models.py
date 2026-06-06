import subprocess
import sys
import unittest
from pathlib import Path
from typing import get_args

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)

from model.agent_run import ACTIVE_RUN_STATUSES, AgentRun, AgentRunStatus
from model.agent_run_event import AgentRunEvent
from model.approval import (
    ApprovalBatch,
    ApprovalBatchStatus,
    ApprovalRequest,
    ApprovalRequestDecision,
)
from model.message_part import MessagePart
from model.outbox_event import OutboxEvent, OutboxEventStatus
from model.tool_invocation import ToolInvocation, ToolInvocationStatus


class HitlModelTest(unittest.TestCase):
    def test_agent_run_has_required_state_and_lease_columns(self) -> None:
        table = AgentRun.__table__

        self.assertEqual(table.name, "agent_runs")
        self.assertGreaterEqual(
            set(table.columns.keys()),
            {
                "id",
                "conversation_id",
                "user_message_id",
                "assistant_message_id",
                "status",
                "version",
                "lease_owner",
                "lease_expires_at",
                "active_command_id",
                "error",
                "created_at",
                "updated_at",
                "completed_at",
            },
        )
        self.assertTrue(table.c.id.primary_key)
        self.assertFalse(table.c.conversation_id.nullable)
        self.assertFalse(table.c.user_message_id.nullable)
        self.assertFalse(table.c.assistant_message_id.nullable)
        self.assertFalse(table.c.status.nullable)
        self.assertFalse(table.c.version.nullable)
        self.assertIsInstance(table.c.version.type, Integer)
        self.assertIsInstance(table.c.error.type, Text)
        self.assertIsInstance(table.c.created_at.type, DateTime)
        self.assertIsInstance(table.c.updated_at.type, DateTime)
        self.assertTrue(table.c.created_at.type.timezone)
        self.assertTrue(table.c.updated_at.type.timezone)

    def test_active_run_unique_index_is_partial(self) -> None:
        index = next(
            item
            for item in AgentRun.__table__.indexes
            if item.name == "uq_agent_runs_active_conversation"
        )

        self.assertTrue(index.unique)
        where_clause = str(index.dialect_options["postgresql"]["where"])
        self.assertIn("queued", where_clause)
        self.assertIn("running", where_clause)
        self.assertIn("awaiting_approval", where_clause)
        self.assertIn("resume_queued", where_clause)
        self.assertIn("resuming", where_clause)
        self.assertEqual(
            ACTIVE_RUN_STATUSES,
            ("queued", "running", "awaiting_approval", "resume_queued", "resuming"),
        )

    def test_agent_run_status_type_covers_all_states(self) -> None:
        self.assertEqual(
            set(get_args(AgentRunStatus)),
            {
                "queued",
                "running",
                "awaiting_approval",
                "resume_queued",
                "resuming",
                "completed",
                "failed",
            },
        )

    def test_importing_agent_run_registers_approval_batch_mapper(self) -> None:
        script = """
from sqlalchemy.orm import configure_mappers

from model.agent_run import AgentRun

configure_mappers()

assert AgentRun.approval_batches.property.mapper.class_.__name__ == "ApprovalBatch"
"""

        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_approval_batches_have_run_sequence_uniqueness(self) -> None:
        table = ApprovalBatch.__table__
        unique_constraints = {
            tuple(column.name for column in constraint.columns)
            for constraint in table.constraints
            if isinstance(constraint, UniqueConstraint)
        }

        self.assertEqual(table.name, "approval_batches")
        self.assertIn(("agent_run_id", "sequence"), unique_constraints)
        self.assertFalse(table.c.agent_run_id.nullable)
        self.assertFalse(table.c.assistant_message_id.nullable)
        self.assertFalse(table.c.interrupt_id.nullable)
        self.assertFalse(table.c.sequence.nullable)
        self.assertFalse(table.c.status.nullable)
        self.assertFalse(table.c.expires_at.nullable)
        self.assertTrue(table.c.expires_at.type.timezone)
        self.assertEqual(
            set(get_args(ApprovalBatchStatus)),
            {"pending", "resolved", "expired"},
        )

    def test_approval_requests_have_order_uniqueness_and_snapshots(self) -> None:
        table = ApprovalRequest.__table__
        unique_constraints = {
            tuple(column.name for column in constraint.columns)
            for constraint in table.constraints
            if isinstance(constraint, UniqueConstraint)
        }

        self.assertEqual(table.name, "approval_requests")
        self.assertIn(("approval_batch_id", "order_index"), unique_constraints)
        self.assertFalse(table.c.approval_batch_id.nullable)
        self.assertFalse(table.c.tool_invocation_id.nullable)
        self.assertFalse(table.c.order_index.nullable)
        self.assertFalse(table.c.tool_name.nullable)
        self.assertFalse(table.c.args.nullable)
        self.assertFalse(table.c.decision.nullable)
        self.assertIsInstance(table.c.args.type, JSON)
        self.assertEqual(
            set(get_args(ApprovalRequestDecision)),
            {"pending", "approved", "rejected", "expired"},
        )

    def test_agent_run_events_id_is_monotonic_bigint(self) -> None:
        table = AgentRunEvent.__table__

        self.assertEqual(table.name, "agent_run_events")
        self.assertTrue(table.c.id.primary_key)
        self.assertTrue(table.c.id.autoincrement)
        self.assertIsInstance(table.c.id.type, BigInteger)
        self.assertFalse(table.c.agent_run_id.nullable)
        self.assertFalse(table.c.event_type.nullable)
        self.assertFalse(table.c.payload.nullable)
        self.assertIsInstance(table.c.payload.type, JSON)

    def test_outbox_events_id_is_mq_message_id(self) -> None:
        table = OutboxEvent.__table__

        self.assertEqual(table.name, "outbox_events")
        self.assertTrue(table.c.id.primary_key)
        self.assertIsInstance(table.c.id.type, String)
        self.assertFalse(table.c.event_type.nullable)
        self.assertFalse(table.c.aggregate_id.nullable)
        self.assertFalse(table.c.payload.nullable)
        self.assertFalse(table.c.status.nullable)
        self.assertFalse(table.c.attempt_count.nullable)
        self.assertFalse(table.c.available_at.nullable)
        self.assertIsInstance(table.c.last_error.type, Text)
        self.assertEqual(
            set(get_args(OutboxEventStatus)),
            {"pending", "publishing", "published"},
        )

    def test_message_part_can_reference_approval_batch(self) -> None:
        column = MessagePart.__table__.c.approval_batch_id
        foreign_key = next(iter(column.foreign_keys))

        self.assertTrue(column.nullable)
        self.assertEqual(foreign_key.column.table.name, "approval_batches")
        self.assertEqual(foreign_key.ondelete, "SET NULL")

    def test_tool_invocation_status_type_covers_hitl_values_without_db_constraint(
        self,
    ) -> None:
        self.assertEqual(
            set(get_args(ToolInvocationStatus)),
            {
                "awaiting_approval",
                "running",
                "completed",
                "error",
                "rejected",
                "expired",
            },
        )
        self.assertFalse(ToolInvocation.__table__.c.status.nullable)
        self.assertIsInstance(ToolInvocation.__table__.c.status.type, String)
        self.assertFalse(
            any(
                isinstance(constraint, CheckConstraint)
                for constraint in ToolInvocation.__table__.constraints
            )
        )


if __name__ == "__main__":
    unittest.main()
