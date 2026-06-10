import json
import unittest

from schema.chat import DeltaEvent
from service.sse import to_sse


class SseFormattingTest(unittest.TestCase):
    def test_to_sse_serializes_frontend_aliases(self) -> None:
        frame = to_sse(
            DeltaEvent(
                type="delta",
                runId="run-1",
                messageId="assistant-1",
                text="hello",
            ),
            event_id=42,
        )

        self.assertTrue(frame.startswith("id: 42\n"))
        self.assertTrue(frame.endswith("\n\n"))
        payload = json.loads(frame.split("data: ", 1)[1])
        self.assertEqual(
            payload,
            {
                "type": "delta",
                "runId": "run-1",
                "messageId": "assistant-1",
                "text": "hello",
            },
        )

    def test_to_sse_omits_event_id_when_absent(self) -> None:
        frame = to_sse(
            DeltaEvent(
                type="delta",
                runId="run-1",
                messageId="assistant-1",
                text="hello",
            )
        )

        self.assertFalse(frame.startswith("id:"))
        self.assertTrue(frame.startswith("data: "))
