import subprocess
import sys
import unittest
from pathlib import Path
from typing import get_origin

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped

from model.base import Base
from model.message import Message
from model.message_part import MessagePart
from model.tool_invocation import ToolInvocation


class MessageModelTest(unittest.TestCase):
    def test_defines_messages_table_columns(self) -> None:
        table = Message.__table__

        self.assertEqual(table.name, "messages")
        self.assertEqual(
            set(table.columns.keys()),
            {
                "id",
                "conversation_id",
                "role",
                "content",
                "reasoning",
                "status",
                "created_at",
            },
        )
        self.assertTrue(table.c.id.primary_key)
        self.assertFalse(table.c.conversation_id.nullable)
        self.assertTrue(table.c.conversation_id.index)
        self.assertFalse(table.c.role.nullable)
        self.assertFalse(table.c.content.nullable)
        self.assertFalse(table.c.reasoning.nullable)
        self.assertFalse(table.c.status.nullable)
        self.assertFalse(table.c.created_at.nullable)
        self.assertIsInstance(table.c.id.type, String)
        self.assertIsInstance(table.c.content.type, Text)
        self.assertIsInstance(table.c.reasoning.type, Text)
        self.assertIsInstance(table.c.created_at.type, DateTime)

    def test_tool_invocations_table_is_registered(self) -> None:
        table = ToolInvocation.__table__

        self.assertIs(table, Base.metadata.tables["tool_invocations"])
        self.assertTrue(table.c.id.primary_key)
        self.assertIn("message_id", table.c)
        self.assertIn("tool_name", table.c)
        self.assertIn("args", table.c)
        self.assertIn("result", table.c)
        self.assertIn("error", table.c)
        self.assertIn("latency_ms", table.c)
        self.assertIn("status", table.c)
        self.assertIn("created_at", table.c)

    def test_message_parts_table_is_registered(self) -> None:
        table = MessagePart.__table__

        self.assertIs(table, Base.metadata.tables["message_parts"])
        self.assertTrue(table.c.id.primary_key)
        self.assertIn("message_id", table.c)
        self.assertIn("type", table.c)
        self.assertIn("order_index", table.c)
        self.assertIn("text", table.c)
        self.assertIn("tool_invocation_id", table.c)
        self.assertIn("created_at", table.c)

    def test_importing_message_registers_related_mappers(self) -> None:
        script = """
from sqlalchemy.orm import configure_mappers

from model.base import Base
from model.message import Message

configure_mappers()

assert "tool_invocations" in Base.metadata.tables
assert "message_parts" in Base.metadata.tables
assert Message.tool_invocations.property.mapper.class_.__name__ == "ToolInvocation"
assert Message.timeline_parts.property.mapper.class_.__name__ == "MessagePart"
"""

        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_relationships_use_sqlalchemy_mapped_annotations(self) -> None:
        self.assertIs(get_origin(Message.__annotations__["tool_invocations"]), Mapped)
        self.assertIs(get_origin(Message.__annotations__["timeline_parts"]), Mapped)
        self.assertIs(get_origin(ToolInvocation.__annotations__["message"]), Mapped)
        self.assertIs(get_origin(MessagePart.__annotations__["message"]), Mapped)
        self.assertIs(get_origin(MessagePart.__annotations__["tool_invocation"]), Mapped)

    def test_message_part_tool_invocation_fk_sets_null_on_delete(self) -> None:
        foreign_key = next(
            iter(MessagePart.__table__.c.tool_invocation_id.foreign_keys)
        )

        self.assertEqual(foreign_key.ondelete, "SET NULL")

    def test_migration_sets_message_part_tool_invocation_fk_null_on_delete(self) -> None:
        migration_path = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "versions"
            / "936cc28dfdbd_create_tool_invocations_and_message_.py"
        )

        migration = migration_path.read_text()

        self.assertIn(
            "['tool_invocation_id'], ['tool_invocations.id'], ondelete='SET NULL'",
            migration,
        )
        self.assertNotIn(
            "['tool_invocation_id'], ['tool_invocations.id'], ondelete='CASCADE'",
            migration,
        )


if __name__ == "__main__":
    unittest.main()
