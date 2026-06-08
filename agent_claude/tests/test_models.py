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


if __name__ == "__main__":
    unittest.main()
