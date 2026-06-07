import assert from "node:assert/strict";
import test from "node:test";
import {
	appendReasoningTimelinePart,
	getLatestStreamingAssistantMessageId,
	getRenderableTimelineParts,
	getResumableStreamingMessageId,
	getVisibleMessageWindow,
	isActiveConversationStreaming,
	isConversationInputLocked,
	resetStreamCreatedMessage,
	resolveLoadedConversationMessages,
	upsertToolTimelinePart,
} from "./chat-ui-state";

test("isActiveConversationStreaming only locks the active conversation", () => {
	assert.equal(
		isActiveConversationStreaming({
			activeConversationId: "new-chat",
			isStreaming: true,
			streamingConversationId: "old-chat",
		}),
		false,
	);

	assert.equal(
		isActiveConversationStreaming({
			activeConversationId: undefined,
			isStreaming: true,
			streamingConversationId: "old-chat",
		}),
		false,
	);

	assert.equal(
		isActiveConversationStreaming({
			activeConversationId: "old-chat",
			isStreaming: true,
			streamingConversationId: "old-chat",
		}),
		true,
	);
});

test("isConversationInputLocked locks only the conversation with an active run", () => {
	const state = {
		runsByConversationId: {
			"conversation-1": {
				runId: "run-1",
				assistantMessageId: "assistant-1",
				status: "awaiting_approval" as const,
			},
		},
	};

	assert.equal(isConversationInputLocked(state, "conversation-1"), true);
	assert.equal(isConversationInputLocked(state, "conversation-2"), false);
	assert.equal(isConversationInputLocked(state, undefined), false);
});

test("getVisibleMessageWindow returns the latest bounded message slice", () => {
	const messages = Array.from(
		{ length: 120 },
		(_, index) => `message-${index}`,
	);

	assert.deepEqual(getVisibleMessageWindow(messages, 50), {
		hiddenCount: 70,
		messages: messages.slice(70),
		startIndex: 70,
		totalCount: 120,
	});
});

test("getVisibleMessageWindow keeps all messages when the window covers them", () => {
	const messages = Array.from({ length: 20 }, (_, index) => `message-${index}`);

	assert.deepEqual(getVisibleMessageWindow(messages, 80), {
		hiddenCount: 0,
		messages,
		startIndex: 0,
		totalCount: 20,
	});
});

test("resolveLoadedConversationMessages keeps existing streamed replay over stale loads", () => {
	const existingMessages = [
		{ id: "assistant-1", content: "first second", status: "streaming" },
	];
	const loadedMessages = [
		{ id: "assistant-1", content: "", status: "streaming" },
	];

	assert.equal(
		resolveLoadedConversationMessages({
			existingMessages,
			loadedMessages,
		}),
		existingMessages,
	);
});

test("getLatestStreamingAssistantMessageId returns the newest streaming assistant", () => {
	assert.equal(
		getLatestStreamingAssistantMessageId([
			{ id: "user-1", role: "user", status: "done" },
			{ id: "assistant-old", role: "assistant", status: "streaming" },
			{ id: "assistant-done", role: "assistant", status: "done" },
			{ id: "assistant-new", role: "assistant", status: "streaming" },
		]),
		"assistant-new",
	);
});

test("getLatestStreamingAssistantMessageId ignores user and done messages", () => {
	assert.equal(
		getLatestStreamingAssistantMessageId([
			{ id: "user-streaming", role: "user", status: "streaming" },
			{ id: "assistant-done", role: "assistant", status: "done" },
			{ id: "assistant-error", role: "assistant", status: "error" },
		]),
		undefined,
	);
});

test("resetStreamCreatedMessage resets streamed text before full replay", () => {
	assert.deepEqual(
		resetStreamCreatedMessage(
			{
				id: "assistant-1",
				conversationId: "conversation-1",
				role: "assistant",
				content: "already shown",
				reasoning: "reasoning shown",
				status: "streaming",
				createdAt: "2026-01-01T00:00:00.000Z",
			},
			{
				id: "assistant-1",
				conversationId: "conversation-1",
				role: "assistant",
				content: "",
				status: "streaming",
				createdAt: "2026-01-01T00:00:00.000Z",
			},
		),
		{
			id: "assistant-1",
			conversationId: "conversation-1",
			role: "assistant",
			content: "",
			status: "streaming",
			createdAt: "2026-01-01T00:00:00.000Z",
		},
	);
});

test("getResumableStreamingMessageId resumes cached streaming messages", () => {
	assert.equal(
		getResumableStreamingMessageId({
			messages: [{ id: "assistant-1", role: "assistant", status: "streaming" }],
			isStreaming: false,
		}),
		"assistant-1",
	);
});

test("getResumableStreamingMessageId skips the currently connected stream", () => {
	assert.equal(
		getResumableStreamingMessageId({
			messages: [{ id: "assistant-1", role: "assistant", status: "streaming" }],
			isStreaming: true,
			streamingMessageId: "assistant-1",
		}),
		undefined,
	);
});

test("appendReasoningTimelinePart preserves reasoning event order", () => {
	const parts = appendReasoningTimelinePart(
		[
			{
				id: "tool-1",
				type: "tool" as const,
				invocation: {
					id: "tool-1",
					messageId: "assistant-1",
					toolName: "web_search",
					args: { query: "market" },
					status: "running" as const,
				},
			},
		],
		{ id: "reasoning-2", text: "Compare results." },
	);

	assert.deepEqual(
		parts.map((part) => part.id),
		["tool-1", "reasoning-2"],
	);
	assert.deepEqual(parts[1], {
		id: "reasoning-2",
		type: "reasoning",
		text: "Compare results.",
	});
});

test("appendReasoningTimelinePart merges adjacent reasoning chunks", () => {
	const parts = appendReasoningTimelinePart(
		[{ id: "reasoning-1", type: "reasoning" as const, text: "Search " }],
		{ id: "reasoning-2", text: "first." },
	);

	assert.deepEqual(parts, [
		{ id: "reasoning-1", type: "reasoning", text: "Search first." },
	]);
});

test("upsertToolTimelinePart updates tool result without moving the original event", () => {
	const parts = upsertToolTimelinePart(
		[
			{ id: "reasoning-1", type: "reasoning" as const, text: "Search first." },
			{
				id: "tool-1",
				type: "tool" as const,
				invocation: {
					id: "tool-1",
					messageId: "assistant-1",
					toolName: "web_search",
					args: { query: "market" },
					status: "running" as const,
				},
			},
			{ id: "reasoning-2", type: "reasoning" as const, text: "Then answer." },
		],
		{
			id: "tool-1",
			messageId: "assistant-1",
			toolName: "web_search",
			args: { query: "market" },
			result: { summary: "2 results" },
			latencyMs: 120,
			status: "completed" as const,
		},
	);

	assert.deepEqual(
		parts.map((part) => part.id),
		["reasoning-1", "tool-1", "reasoning-2"],
	);
	assert.equal(parts[1].type, "tool");
	if (parts[1].type === "tool") {
		assert.deepEqual(parts[1].invocation.result, { summary: "2 results" });
		assert.equal(parts[1].invocation.status, "completed");
	}
});

test("getRenderableTimelineParts keeps approval parts distinct from tool parts", () => {
	const parts = getRenderableTimelineParts([
		{
			id: "approval-part-1",
			type: "approval" as const,
			orderIndex: 2,
			batch: {
				id: "batch-1",
				status: "pending" as const,
				expiresAt: "2026-01-01T00:30:00.000Z",
				requests: [
					{
						id: "request-1",
						toolInvocationId: "tool-1",
						toolName: "get_weather",
						args: { city: "Beijing" },
						decision: "pending" as const,
					},
				],
			},
		},
		{
			id: "reasoning-1",
			type: "reasoning" as const,
			orderIndex: 1,
			text: "Check weather.",
		},
	]);

	assert.deepEqual(
		parts.map((part) => part.type),
		["reasoning", "approval"],
	);
	if (parts[1]?.type === "approval") {
		assert.equal(parts[1].batch.requests[0]?.toolName, "get_weather");
	}
});
