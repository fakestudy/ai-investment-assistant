import unittest

from model.base import Base
import model.agent_session  # noqa: F401
import model.agent_session_entry  # noqa: F401
import model.conversation  # noqa: F401
import model.message  # noqa: F401
import model.message_part  # noqa: F401
import model.tool_invocation  # noqa: F401


class ModelMetadataTest(unittest.TestCase):
    def test_expected_tables_are_registered(self) -> None:
        expected = {
            "conversations",
            "messages",
            "tool_invocations",
            "message_parts",
            "agent_sessions",
            "agent_session_entries",
        }

        self.assertTrue(expected.issubset(set(Base.metadata.tables)))

    def test_agent_session_entries_has_uuid_idempotency_index(self) -> None:
        table = Base.metadata.tables["agent_session_entries"]
        index = next(
            idx
            for idx in table.indexes
            if idx.name == "ix_agent_session_entries_session_entry_uuid"
        )

        self.assertTrue(index.unique)
        self.assertEqual(
            [column.name for column in index.columns],
            ["project_key", "sdk_session_id", "subpath", "entry_uuid"],
        )
        self.assertFalse(table.c.subpath.nullable)
        self.assertTrue(table.c.entry_uuid.nullable)


if __name__ == "__main__":
    unittest.main()
