import assert from "node:assert/strict";
import test from "node:test";
import {
	type ChatEventReducerState,
	reduceChatStreamEvent,
} from "./chat-event-reducer";

const baseState = (): ChatEventReducerState => ({
	messages: [
		{
			id: "assistant-1",
			conversationId: "conversation-1",
			role: "assistant",
			content: "",
			status: "streaming",
			createdAt: "2026-01-01T00:00:00.000Z",
		},
	],
});

const pendingApprovalPart = {
	id: "approval-part-1",
	type: "approval" as const,
	orderIndex: 1,
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
};

test("ignores event ids that are not newer than the cursor", () => {
	const state: ChatEventReducerState = {
		...baseState(),
		activeRun: {
			runId: "run-1",
			assistantMessageId: "assistant-1",
			status: "streaming",
			lastEventId: 42,
		},
	};

	const nextState = reduceChatStreamEvent(state, {
		eventId: 42,
		event: {
			type: "delta",
			runId: "run-1",
			messageId: "assistant-1",
			text: "ignored",
		},
	});

	assert.deepEqual(nextState, state);
});

test("run_created records active run state and cursor", () => {
	const nextState = reduceChatStreamEvent(baseState(), {
		eventId: 40,
		event: {
			type: "run_created",
			runId: "run-1",
			status: "running",
			assistantMessageId: "assistant-1",
		},
	});

	assert.deepEqual(nextState.activeRun, {
		runId: "run-1",
		assistantMessageId: "assistant-1",
		status: "streaming",
		lastEventId: 40,
	});
});

test("message_created upserts existing assistant message", () => {
	const nextState = reduceChatStreamEvent(baseState(), {
		eventId: 41,
		event: {
			type: "message_created",
			runId: "run-1",
			message: {
				id: "assistant-1",
				conversationId: "conversation-1",
				role: "assistant",
				content: "server reset",
				status: "streaming",
				createdAt: "2026-01-01T00:00:00.000Z",
			},
		},
	});

	assert.equal(nextState.messages.length, 1);
	assert.equal(nextState.messages[0]?.content, "server reset");
});

test("reasoning event appends reasoning text and timeline part", () => {
	const nextState = reduceChatStreamEvent(baseState(), {
		eventId: 42,
		event: {
			type: "reasoning",
			runId: "run-1",
			messageId: "assistant-1",
			text: "thinking",
		},
	});

	assert.equal(nextState.messages[0]?.reasoning, "thinking");
	assert.equal(nextState.messages[0]?.timelineParts?.[0]?.type, "reasoning");
	assert.equal(nextState.messages[0]?.timelineItems?.[0]?.type, "thought");
	if (nextState.messages[0]?.timelineParts?.[0]?.type === "reasoning") {
		assert.equal(nextState.messages[0].timelineParts[0].text, "thinking");
		assert.equal(nextState.messages[0].timelineParts[0].id, "reasoning-42");
	}
	if (nextState.messages[0]?.timelineItems?.[0]?.type === "thought") {
		assert.equal(nextState.messages[0].timelineItems[0].text, "thinking");
		assert.equal(nextState.messages[0].timelineItems[0].id, "reasoning-42");
	}
});

test("tool events upsert tool invocation and timeline item", () => {
	const runningState = reduceChatStreamEvent(baseState(), {
		eventId: 42,
		event: {
			type: "tool_call",
			runId: "run-1",
			messageId: "assistant-1",
			invocation: {
				id: "tool-1",
				messageId: "assistant-1",
				toolName: "get_weather",
				args: { city: "Beijing" },
				status: "running",
			},
		},
	});

	const completedState = reduceChatStreamEvent(runningState, {
		eventId: 43,
		event: {
			type: "tool_result",
			runId: "run-1",
			messageId: "assistant-1",
			invocation: {
				id: "tool-1",
				messageId: "assistant-1",
				toolName: "get_weather",
				args: { city: "Beijing" },
				result: { temperature: 20 },
				status: "completed",
			},
		},
	});

	assert.equal(completedState.messages[0]?.toolInvocations?.length, 1);
	assert.equal(
		completedState.messages[0]?.toolInvocations?.[0]?.status,
		"completed",
	);
	assert.equal(completedState.messages[0]?.timelineParts?.length, 1);
	assert.equal(completedState.messages[0]?.timelineParts?.[0]?.type, "tool");
	assert.equal(completedState.messages[0]?.timelineItems?.length, 1);
	assert.equal(completedState.messages[0]?.timelineItems?.[0]?.type, "tool");
	if (completedState.messages[0]?.timelineParts?.[0]?.type === "tool") {
		assert.equal(
			completedState.messages[0].timelineParts[0].invocation.status,
			"completed",
		);
	}
	if (completedState.messages[0]?.timelineItems?.[0]?.type === "tool") {
		assert.equal(
			completedState.messages[0].timelineItems[0].invocation.status,
			"completed",
		);
	}
});

test("approval_required marks matching tool item and moves run to awaiting approval", () => {
	const stateWithTool = reduceChatStreamEvent(
		{
			...baseState(),
			activeRun: {
				runId: "run-1",
				assistantMessageId: "assistant-1",
				status: "streaming",
				lastEventId: 40,
			},
		},
		{
			eventId: 41,
			event: {
				type: "tool_call",
				runId: "run-1",
				messageId: "assistant-1",
				invocation: {
					id: "tool-1",
					messageId: "assistant-1",
					toolName: "get_weather",
					args: { city: "Beijing" },
					status: "running",
				},
			},
		},
	);

	const nextState = reduceChatStreamEvent(stateWithTool, {
		eventId: 42,
		event: {
			type: "approval_required",
			runId: "run-1",
			messageId: "assistant-1",
			part: pendingApprovalPart,
		},
	});

	assert.equal(nextState.activeRun?.status, "awaiting_approval");
	assert.equal(nextState.activeRun?.lastEventId, 42);
	assert.deepEqual(
		nextState.activeRun?.approvalBatch,
		pendingApprovalPart.batch,
	);
	assert.equal(
		nextState.messages[0]?.timelineParts?.some(
			(part) => part.type === "approval",
		),
		false,
	);
	const item = nextState.messages[0]?.timelineItems?.[0];
	assert.equal(item?.type, "tool");
	if (item?.type === "tool") {
		assert.equal(item.invocation.status, "awaiting_approval");
		assert.equal(item.approval?.requestId, "request-1");
		assert.equal(item.approval?.batchId, "batch-1");
	}
});

test("approval_required creates a tool item when approval arrives before tool_call", () => {
	const nextState = reduceChatStreamEvent(
		{
			...baseState(),
			activeRun: {
				runId: "run-1",
				assistantMessageId: "assistant-1",
				status: "streaming",
				lastEventId: 40,
			},
		},
		{
			eventId: 41,
			event: {
				type: "approval_required",
				runId: "run-1",
				messageId: "assistant-1",
				part: pendingApprovalPart,
			},
		},
	);

	const item = nextState.messages[0]?.timelineItems?.[0];
	assert.equal(item?.type, "tool");
	if (item?.type === "tool") {
		assert.equal(item.invocation.id, "tool-1");
		assert.equal(item.invocation.toolName, "get_weather");
		assert.equal(item.invocation.status, "awaiting_approval");
		assert.equal(item.approval?.requestId, "request-1");
	}
});

test("approval_resolved marks tool approval readonly and moves run to resuming", () => {
	const resolvedBatch = {
		...pendingApprovalPart.batch,
		status: "resolved" as const,
		resolutionSource: "manual" as const,
		resolvedAt: "2026-01-01T00:02:00.000Z",
		requests: [
			{
				...pendingApprovalPart.batch.requests[0],
				decision: "approved" as const,
				decidedAt: "2026-01-01T00:02:00.000Z",
			},
		],
	};

	const nextState = reduceChatStreamEvent(
		{
			messages: [
				{
					...baseState().messages[0],
					timelineItems: [
						{
							id: "tool-1",
							type: "tool" as const,
							invocation: {
								id: "tool-1",
								messageId: "assistant-1",
								toolName: "get_weather",
								args: { city: "Beijing" },
								status: "awaiting_approval" as const,
							},
							approval: {
								batchId: "batch-1",
								requestId: "request-1",
								status: "pending" as const,
								decision: "pending" as const,
								expiresAt: "2026-01-01T00:30:00.000Z",
							},
						},
					],
				},
			],
			activeRun: {
				runId: "run-1",
				assistantMessageId: "assistant-1",
				status: "awaiting_approval",
				lastEventId: 41,
				approvalBatch: pendingApprovalPart.batch,
			},
		},
		{
			eventId: 42,
			event: {
				type: "approval_resolved",
				runId: "run-1",
				batch: resolvedBatch,
			},
		},
	);

	assert.equal(nextState.activeRun?.status, "resuming");
	assert.equal(nextState.activeRun?.lastEventId, 42);
	assert.equal(nextState.activeRun?.approvalBatch?.status, "resolved");
	const item = nextState.messages[0]?.timelineItems?.[0];
	assert.equal(item?.type, "tool");
	if (item?.type === "tool") {
		assert.equal(item.approval?.status, "resolved");
		assert.equal(item.approval?.decision, "approved");
	}
});

test("terminal run events clear active run state", () => {
	const state: ChatEventReducerState = {
		...baseState(),
		activeRun: {
			runId: "run-1",
			assistantMessageId: "assistant-1",
			status: "resuming",
			lastEventId: 42,
		},
	};

	const doneState = reduceChatStreamEvent(state, {
		eventId: 43,
		event: { type: "done", runId: "run-1", messageId: "assistant-1" },
	});
	const errorState = reduceChatStreamEvent(state, {
		eventId: 44,
		event: { type: "error", runId: "run-1", message: "failed" },
	});

	assert.equal(doneState.activeRun, undefined);
	assert.equal(doneState.messages[0]?.status, "done");
	assert.equal(errorState.activeRun, undefined);
});
