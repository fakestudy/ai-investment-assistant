import unittest

from sqlalchemy import DateTime, String, Text

from model.message import Message


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


if __name__ == "__main__":
    unittest.main()
