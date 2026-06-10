import assert from "node:assert/strict";
import test from "node:test";

function mockJsonFetch() {
	const calls: Array<{ input: string | URL | Request; init?: RequestInit }> =
		[];

	globalThis.fetch = async (input, init) => {
		calls.push({ input, init });
		return new Response(
			JSON.stringify({
				id: "conversation-1",
				title: "Updated title",
				createdAt: "2026-01-01T00:00:00.000Z",
				updatedAt: "2026-01-01T00:00:00.000Z",
			}),
			{
				status: 200,
				headers: { "Content-Type": "application/json" },
			},
		);
	};

	return calls;
}

async function loadApi() {
	return import(new URL("./api.ts", import.meta.url).href) as Promise<
		typeof import("./api")
	>;
}

test("renameConversation posts backend conversation_id payload", async () => {
	const calls = mockJsonFetch();
	const { renameConversation } = await loadApi();

	await renameConversation("conversation-1", "Updated title");

	assert.equal(
		String(calls[0].input),
		"http://localhost:3000/api/conversation/title/update",
	);
	assert.equal(calls[0].init?.method, "POST");
	assert.equal(
		calls[0].init?.body,
		JSON.stringify({
			conversation_id: "conversation-1",
			title: "Updated title",
		}),
	);
});

test("deleteConversation posts backend conversation_id payload", async () => {
	const calls = mockJsonFetch();
	const { deleteConversation } = await loadApi();

	await deleteConversation("conversation-1");

	assert.equal(
		String(calls[0].input),
		"http://localhost:3000/api/conversation/delete",
	);
	assert.equal(calls[0].init?.method, "POST");
	assert.equal(
		calls[0].init?.body,
		JSON.stringify({
			conversation_id: "conversation-1",
		}),
	);
});

test("listMessages returns backend messages envelope with activeRun", async () => {
	const calls: Array<{ input: string | URL | Request; init?: RequestInit }> =
		[];
	globalThis.fetch = async (input, init) => {
		calls.push({ input, init });
		return new Response(
			JSON.stringify({
				messages: [
					{
						id: "assistant-1",
						conversationId: "conversation-1",
						role: "assistant",
						content: "hello",
						status: "done",
						createdAt: "2026-01-01T00:00:00.000Z",
					},
				],
				activeRun: {
					runId: "run-1",
					status: "awaiting_approval",
					lastEventId: 42,
					assistantMessageId: "assistant-1",
					approvalBatch: undefined,
				},
			}),
			{
				status: 200,
				headers: { "Content-Type": "application/json" },
			},
		);
	};
	const { listMessages } = await loadApi();

	const response = await listMessages("conversation-1");

	assert.equal(
		String(calls[0].input),
		"http://localhost:3000/api/conversation/messages/conversation-1",
	);
	assert.equal(response.messages[0]?.id, "assistant-1");
	assert.equal(response.activeRun?.runId, "run-1");
});

test("editMessage patches message content", async () => {
	const calls: Array<{ input: string | URL | Request; init?: RequestInit }> =
		[];
	globalThis.fetch = async (input, init) => {
		calls.push({ input, init });
		return new Response(
			JSON.stringify({
				id: "user-1",
				conversationId: "conversation-1",
				role: "user",
				content: "updated question",
				status: "done",
				createdAt: "2026-01-01T00:00:00.000Z",
			}),
			{
				status: 200,
				headers: { "Content-Type": "application/json" },
			},
		);
	};
	const { editMessage } = await loadApi();

	const response = await editMessage("user-1", "updated question");

	assert.equal(
		String(calls[0].input),
		"http://localhost:3000/api/messages/user-1",
	);
	assert.equal(calls[0].init?.method, "PATCH");
	assert.equal(
		calls[0].init?.body,
		JSON.stringify({ content: "updated question" }),
	);
	assert.equal(response.content, "updated question");
});

test("cancelChatStream posts cancel URL", async () => {
	const calls: Array<{ input: string | URL | Request; init?: RequestInit }> =
		[];
	globalThis.fetch = async (input, init) => {
		calls.push({ input, init });
		return new Response(null, { status: 204 });
	};
	const { cancelChatStream } = await loadApi();

	await cancelChatStream("assistant-1");

	assert.equal(
		String(calls[0].input),
		"http://localhost:3000/api/chat/streams/assistant-1/cancel",
	);
	assert.equal(calls[0].init?.method, "POST");
});

test("resumeChatStream uses POST run cursor payload", async () => {
	const calls: Array<{ input: string | URL | Request; init?: RequestInit }> =
		[];
	globalThis.fetch = async (input, init) => {
		calls.push({ input, init });
		return new Response("", {
			status: 200,
			headers: { "Content-Type": "text/event-stream" },
		});
	};
	const { resumeChatStream } = await loadApi();

	await resumeChatStream(
		{ runId: "run-1", afterEventId: 42 },
		{ signal: new AbortController().signal, onEvent: () => undefined },
	);

	assert.equal(
		String(calls[0].input),
		"http://localhost:3000/api/chat/stream/resume",
	);
	assert.equal(calls[0].init?.method, "POST");
	assert.equal(
		calls[0].init?.body,
		JSON.stringify({ runId: "run-1", afterEventId: 42 }),
	);
});

test("streamChat uses POST chat payload", async () => {
	const calls: Array<{ input: string | URL | Request; init?: RequestInit }> =
		[];
	globalThis.fetch = async (input, init) => {
		calls.push({ input, init });
		return new Response("", {
			status: 200,
			headers: { "Content-Type": "text/event-stream" },
		});
	};
	const { streamChat } = await loadApi();

	await streamChat(
		{ conversationId: "conversation-1", message: "hello", generateTitle: true },
		{ signal: new AbortController().signal, onEvent: () => undefined },
	);

	assert.equal(String(calls[0].input), "http://localhost:3000/api/chat/stream");
	assert.equal(calls[0].init?.method, "POST");
	assert.equal(
		calls[0].init?.body,
		JSON.stringify({
			conversationId: "conversation-1",
			message: "hello",
			generateTitle: true,
		}),
	);
});

test("submitApprovalDecisions posts decisions before cursor to batch URL", async () => {
	const calls: Array<{ input: string | URL | Request; init?: RequestInit }> =
		[];
	globalThis.fetch = async (input, init) => {
		calls.push({ input, init });
		return new Response("", {
			status: 200,
			headers: { "Content-Type": "text/event-stream" },
		});
	};
	const { submitApprovalDecisions } = await loadApi();

	await submitApprovalDecisions(
		"batch-1",
		{
			decisions: [{ approvalRequestId: "request-1", decision: "approve" }],
			afterEventId: 43,
		},
		{ signal: new AbortController().signal, onEvent: () => undefined },
	);

	assert.equal(
		String(calls[0].input),
		"http://localhost:3000/api/chat/approval/decisions/batch-1",
	);
	assert.equal(calls[0].init?.method, "POST");
	assert.equal(
		calls[0].init?.body,
		JSON.stringify({
			decisions: [{ approvalRequestId: "request-1", decision: "approve" }],
			afterEventId: 43,
		}),
	);
});

test("readSseResponse exposes numeric event id", async () => {
	globalThis.fetch = async () =>
		new Response(
			[
				"id: 43",
				'data: {"type":"done","runId":"run-1","messageId":"assistant-1"}',
				"",
			].join("\n"),
			{
				status: 200,
				headers: { "Content-Type": "text/event-stream" },
			},
		);
	const received: Array<{
		eventId?: number;
		event: { type: string; runId: string; messageId: string };
	}> = [];
	const { streamChat } = await loadApi();

	await streamChat(
		{ conversationId: "conversation-1", message: "hello" },
		{
			signal: new AbortController().signal,
			onEvent: (event) => received.push(event as (typeof received)[number]),
		},
	);

	assert.equal(received[0]?.eventId, 43);
	assert.equal(received[0]?.event.type, "done");
});

test("stream endpoints throw ChatApiError with status on conflict", async () => {
	globalThis.fetch = async () => new Response("conflict", { status: 409 });
	const { ChatApiError, streamChat } = await loadApi();

	await assert.rejects(
		() =>
			streamChat(
				{ conversationId: "conversation-1", message: "hello" },
				{ signal: new AbortController().signal, onEvent: () => undefined },
			),
		(error) => error instanceof ChatApiError && error.status === 409,
	);
});

test("json endpoints preserve backend detail without changing safe error message", async () => {
	globalThis.fetch = async () =>
		new Response(
			JSON.stringify({ detail: "Only user messages can be edited" }),
			{
				status: 400,
				headers: { "Content-Type": "application/json" },
			},
		);
	const { ChatApiError, editMessage } = await loadApi();

	await assert.rejects(
		() => editMessage("assistant-1", "updated"),
		(error) =>
			error instanceof ChatApiError &&
			error.status === 400 &&
			error.responseMessage === "Only user messages can be edited" &&
			error.message === "Request failed with status 400",
	);
});
