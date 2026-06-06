import unittest

from pydantic import TypeAdapter, ValidationError

from schema.chat import (
    ActiveRunSummary,
    ApprovalBatchPayload,
    ApprovalDecisionRequest,
    ApprovalRequestPayload,
    ApprovalResolvedEvent,
    ApprovalTimelinePart,
    ChatStreamResponse,
    ChatStreamResumeRequest,
    ConversationMessagesResponse,
    RunCreatedEvent,
)


class HitlSchemaTest(unittest.TestCase):
    def test_approval_timeline_part_uses_frontend_aliases(self) -> None:
        payload = ApprovalTimelinePart(
            id="part-1",
            type="approval",
            order_index=2,
            batch=ApprovalBatchPayload(
                id="batch-1",
                status="pending",
                expires_at="2026-06-06T12:30:00Z",
                requests=[],
            ),
        ).model_dump(by_alias=True)

        self.assertEqual(payload["orderIndex"], 2)
        self.assertTrue(payload["batch"]["expiresAt"].endswith("Z"))

    def test_decision_request_accepts_only_approve_or_reject(self) -> None:
        with self.assertRaises(ValidationError):
            ApprovalDecisionRequest.model_validate(
                {
                    "decisions": [
                        {"approvalRequestId": "request-1", "decision": "edit"}
                    ],
                    "afterEventId": 1,
                }
            )

    def test_approval_payload_uses_frontend_aliases(self) -> None:
        payload = ApprovalRequestPayload(
            id="request-1",
            tool_invocation_id="tool-1",
            tool_name="get_weather",
            args={"city": "Beijing"},
            decision="pending",
            decided_at=None,
        ).model_dump(by_alias=True, exclude_none=True)

        self.assertEqual(payload["toolInvocationId"], "tool-1")
        self.assertEqual(payload["toolName"], "get_weather")
        self.assertNotIn("decidedAt", payload)

    def test_conversation_messages_response_contains_messages_and_active_run(self) -> None:
        response = ConversationMessagesResponse(
            messages=[],
            active_run=ActiveRunSummary(
                run_id="run-1",
                status="awaiting_approval",
                last_event_id=42,
                assistant_message_id="assistant-1",
                approval_batch=ApprovalBatchPayload(
                    id="batch-1",
                    status="pending",
                    expires_at="2026-06-06T12:30:00Z",
                    requests=[],
                ),
            ),
        )

        payload = response.model_dump(by_alias=True)

        self.assertEqual(set(payload), {"messages", "activeRun"})
        self.assertEqual(payload["activeRun"]["runId"], "run-1")
        self.assertEqual(payload["activeRun"]["lastEventId"], 42)
        self.assertEqual(payload["activeRun"]["approvalBatch"]["id"], "batch-1")

    def test_persisted_stream_events_require_run_id(self) -> None:
        with self.assertRaises(ValidationError):
            RunCreatedEvent.model_validate(
                {
                    "type": "run_created",
                    "status": "queued",
                    "assistantMessageId": "assistant-1",
                }
            )

    def test_chat_stream_response_accepts_hitl_events(self) -> None:
        adapter = TypeAdapter(ChatStreamResponse)
        events = [
            {
                "type": "run_created",
                "runId": "run-1",
                "status": "queued",
                "assistantMessageId": "assistant-1",
            },
            {
                "type": "approval_required",
                "runId": "run-1",
                "messageId": "assistant-1",
                "part": {
                    "id": "part-1",
                    "type": "approval",
                    "orderIndex": 0,
                    "batch": {
                        "id": "batch-1",
                        "status": "pending",
                        "expiresAt": "2026-06-06T12:30:00Z",
                        "requests": [],
                    },
                },
            },
            {
                "type": "approval_resolved",
                "runId": "run-1",
                "batch": {
                    "id": "batch-1",
                    "status": "resolved",
                    "expiresAt": "2026-06-06T12:30:00Z",
                    "resolutionSource": "manual",
                    "resolvedAt": "2026-06-06T12:05:00Z",
                    "requests": [],
                },
            },
        ]

        serialized = [
            adapter.dump_python(
                adapter.validate_python(event),
                by_alias=True,
                exclude_none=True,
            )
            for event in events
        ]

        self.assertEqual(serialized, events)

    def test_resume_request_uses_run_cursor_aliases(self) -> None:
        request = ChatStreamResumeRequest.model_validate(
            {"runId": "run-1", "afterEventId": 42}
        )

        self.assertEqual(request.run_id, "run-1")
        self.assertEqual(request.after_event_id, 42)

    def test_resolved_event_rejects_invalid_batch_status(self) -> None:
        with self.assertRaises(ValidationError):
            ApprovalResolvedEvent.model_validate(
                {
                    "type": "approval_resolved",
                    "runId": "run-1",
                    "batch": {
                        "id": "batch-1",
                        "status": "pending",
                        "expiresAt": "2026-06-06T12:30:00Z",
                        "requests": [],
                    },
                }
            )


if __name__ == "__main__":
    unittest.main()
