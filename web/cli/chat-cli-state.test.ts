import assert from "node:assert/strict";
import test from "node:test";
import type {
	ChatMessage,
	CliStreamState,
	Conversation,
} from "./chat-cli-state";
import {
	createFreshCliBootState,
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

const conversation: Conversation = {
	id: "conversation-1",
	title: "问候",
	createdAt,
	updatedAt: createdAt,
};

test("createFreshCliBootState starts blank even when history exists", () => {
	const bootState = createFreshCliBootState([conversation]);

	assert.deepEqual(bootState.conversations, [conversation]);
	assert.equal(bootState.activeConversationId, undefined);
	assert.deepEqual(bootState.streamState, { messages: [] });
	assert.deepEqual(bootState.noticeLines, [
		"New chat ready. Use /sessions to view history.",
	]);
});

test("parseCliInput maps slash commands and plain text to explicit actions", () => {
	assert.deepEqual(parseCliInput("   "), { type: "empty" });
	assert.deepEqual(parseCliInput("/new"), { type: "new" });
	assert.deepEqual(parseCliInput("/sessions"), { type: "sessions" });
	assert.deepEqual(parseCliInput("/rename Tencent research"), {
		type: "rename",
		title: "Tencent research",
	});
	assert.deepEqual(parseCliInput("/delete"), { type: "delete" });
	assert.deepEqual(parseCliInput("/regenerate"), { type: "regenerate" });
	assert.deepEqual(parseCliInput("/edit #1 updated thesis"), {
		type: "edit",
		target: "#1",
		message: "updated thesis",
	});
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
	assert.deepEqual(parseCliInput("/get-balance"), {
		type: "send",
		message: "/get-balance",
	});
});

test("parseCliInput rejects incomplete argument commands", () => {
	assert.deepEqual(parseCliInput("/rename"), {
		type: "unknown",
		command: "/rename",
	});
	assert.deepEqual(parseCliInput("/edit #1"), {
		type: "unknown",
		command: "/edit",
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
	const batch = {
		id: "batch-1",
		status: "pending" as const,
		expiresAt: "2026-01-01T00:30:00.000Z",
		requests: [
			{
				id: "request-1",
				toolInvocationId: "tool-1",
				toolName: "fetch_url",
				args: { url: "https://example.com" },
				decision: "pending" as const,
			},
		],
	};
	const state: CliStreamState = {
		messages: [
			{
				...assistantMessage,
				timelineParts: [
					{
						id: "approval-part-1",
						type: "approval",
						batch,
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

test("findPendingApprovalBatch falls back to active run approval batch", () => {
	const state: CliStreamState = {
		messages: [assistantMessage],
		activeRun: {
			runId: "run-1",
			assistantMessageId: "assistant-1",
			status: "awaiting_approval",
			lastEventId: 9,
			approvalBatch: {
				id: "batch-from-run",
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
	};

	assert.equal(findPendingApprovalBatch(state)?.id, "batch-from-run");
	assert.equal(getCliStatus(state), "awaiting approval: 1 tool request");
});
