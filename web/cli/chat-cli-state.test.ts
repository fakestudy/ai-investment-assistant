import assert from "node:assert/strict";
import test from "node:test";
import type { ChatMessage, CliStreamState } from "./chat-cli-state";
import {
	findPendingApprovalBatch,
	getCliStatus,
	parseCliInput,
	projectCliStreamEvent,
} from "./chat-cli-state";

const createdAt = "2026-01-01T00:00:00.000Z";

const assistantMessage: ChatMessage = {
	id: "assistant-1",
	conversationId: "conversation-1",
	role: "assistant",
	content: "",
	status: "streaming",
	createdAt,
};

test("parseCliInput maps slash commands and plain text to explicit actions", () => {
	assert.deepEqual(parseCliInput("   "), { type: "empty" });
	assert.deepEqual(parseCliInput("/new"), { type: "new" });
	assert.deepEqual(parseCliInput("/sessions"), { type: "sessions" });
	assert.deepEqual(parseCliInput("/switch abc123"), {
		type: "switch",
		target: "abc123",
	});
	assert.deepEqual(parseCliInput("/stop"), { type: "stop" });
	assert.deepEqual(parseCliInput("/quit"), { type: "quit" });
	assert.deepEqual(parseCliInput("/exit"), { type: "quit" });
	assert.deepEqual(parseCliInput("/help"), { type: "help" });
	assert.deepEqual(parseCliInput("/wat"), {
		type: "unknown",
		command: "/wat",
	});
	assert.deepEqual(parseCliInput("analyze 0700.HK"), {
		type: "send",
		message: "analyze 0700.HK",
	});
});

test("projectCliStreamEvent reuses chat reducer state and tracks title events", () => {
	const started = projectCliStreamEvent(
		{ messages: [], activeRun: undefined },
		{
			eventId: 1,
			event: {
				type: "run_created",
				runId: "run-1",
				status: "running",
				assistantMessageId: "assistant-1",
			},
		},
	);

	assert.equal(started.activeRun?.runId, "run-1");
	assert.equal(started.activeRun?.lastEventId, 1);

	const created = projectCliStreamEvent(started, {
		eventId: 2,
		event: {
			type: "message_created",
			runId: "run-1",
			message: assistantMessage,
		},
	});
	const titled = projectCliStreamEvent(created, {
		eventId: 3,
		event: {
			type: "title",
			runId: "run-1",
			conversationId: "conversation-1",
			title: "Tencent thesis",
		},
	});
	const streamed = projectCliStreamEvent(titled, {
		eventId: 4,
		event: {
			type: "delta",
			runId: "run-1",
			messageId: "assistant-1",
			text: "hello",
		},
	});

	assert.equal(streamed.title, "Tencent thesis");
	assert.equal(streamed.messages[0]?.content, "hello");
	assert.equal(streamed.messages[0]?.status, "streaming");
	assert.equal(streamed.activeRun?.lastEventId, 4);
});

test("findPendingApprovalBatch and getCliStatus expose approval waits", () => {
	const state: CliStreamState = {
		messages: [
			{
				...assistantMessage,
				timelineParts: [
					{
						id: "approval-part-1",
						type: "approval",
						batch: {
							id: "batch-1",
							status: "pending",
							expiresAt: "2026-01-01T00:30:00.000Z",
							requests: [
								{
									id: "request-1",
									toolInvocationId: "tool-1",
									toolName: "fetch_url",
									args: { url: "https://example.com" },
									decision: "pending",
								},
							],
						},
					},
				],
			},
		],
		activeRun: {
			runId: "run-1",
			assistantMessageId: "assistant-1",
			status: "awaiting_approval",
			lastEventId: 9,
		},
	};

	assert.equal(findPendingApprovalBatch(state)?.id, "batch-1");
	assert.equal(getCliStatus(state), "awaiting approval: 1 tool request");
});
