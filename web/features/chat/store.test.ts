import assert from "node:assert/strict";
import test from "node:test";

function conversation(id: string, title: string) {
	return {
		id,
		title,
		createdAt: "2026-01-01T00:00:00.000Z",
		updatedAt: "2026-01-01T00:00:00.000Z",
	};
}

let storeImportCounter = 0;

async function loadStore() {
	storeImportCounter += 1;
	const moduleUrl = new URL(
		`./store.ts?test=${storeImportCounter}`,
		import.meta.url,
	).href;
	return import(moduleUrl) as Promise<typeof import("./store")>;
}

test("loadConversations skips fetch when conversations are already loaded", async () => {
	const { useChatStore } = await loadStore();
	const calls: Array<{ input: string | URL | Request; init?: RequestInit }> =
		[];

	globalThis.fetch = async (input, init) => {
		calls.push({ input, init });
		return new Response(
			JSON.stringify([conversation("conversation-2", "Remote")]),
			{
				status: 200,
				headers: { "Content-Type": "application/json" },
			},
		);
	};

	useChatStore.setState({
		conversations: [conversation("conversation-1", "Local")],
	});

	await useChatStore.getState().loadConversations();

	assert.equal(calls.length, 0);
	assert.deepEqual(useChatStore.getState().conversations, [
		conversation("conversation-1", "Local"),
	]);
});

test("loadConversations force refreshes existing conversations", async () => {
	const { useChatStore } = await loadStore();
	const calls: Array<{ input: string | URL | Request; init?: RequestInit }> =
		[];

	globalThis.fetch = async (input, init) => {
		calls.push({ input, init });
		return new Response(
			JSON.stringify([conversation("conversation-2", "Remote")]),
			{
				status: 200,
				headers: { "Content-Type": "application/json" },
			},
		);
	};

	useChatStore.setState({
		conversations: [conversation("conversation-1", "Local")],
	});

	await useChatStore.getState().loadConversations({ force: true });

	assert.equal(calls.length, 1);
	assert.deepEqual(useChatStore.getState().conversations, [
		conversation("conversation-2", "Remote"),
	]);
});

test("sendMessage force refreshes conversations after stream completes", async () => {
	const { useChatStore } = await loadStore();
	const calls: Array<{ input: string | URL | Request; init?: RequestInit }> =
		[];

	globalThis.fetch = async (input, init) => {
		calls.push({ input, init });
		const url = String(input);

		if (url.endsWith("/api/chat/stream")) {
			return new Response(
				[
					'data: {"type":"message_created","message":{"id":"assistant-1","conversationId":"conversation-1","role":"assistant","content":"","status":"streaming","createdAt":"2026-01-01T00:00:00.000Z"}}',
					'data: {"type":"done","messageId":"assistant-1"}',
					"",
				].join("\n\n"),
				{
					status: 200,
					headers: { "Content-Type": "text/event-stream" },
				},
			);
		}

		return new Response(
			JSON.stringify([conversation("conversation-1", "Synced")]),
			{
				status: 200,
				headers: { "Content-Type": "application/json" },
			},
		);
	};

	useChatStore.setState({
		activeConversationId: "conversation-1",
		conversations: [conversation("conversation-1", "Local")],
		messagesByConversationId: { "conversation-1": [] },
	});

	await useChatStore.getState().sendMessage("hello");
	await new Promise((resolve) => setTimeout(resolve, 0));

	assert.equal(
		calls.filter((call) =>
			String(call.input).endsWith("/api/conversations/list"),
		).length,
		1,
	);
	assert.equal(useChatStore.getState().conversations[0]?.title, "Synced");
});

test("different conversations keep independent stream controllers", async () => {
	const { useChatStore } = await loadStore();
	globalThis.fetch = async (input, init) => {
		const url = String(input);

		if (url.endsWith("/api/chat/stream")) {
			return new Promise<Response>((_resolve, reject) => {
				init?.signal?.addEventListener("abort", () =>
					reject(new DOMException("Aborted", "AbortError")),
				);
			});
		}

		return new Response(
			JSON.stringify([conversation("conversation-1", "First")]),
			{
				status: 200,
				headers: { "Content-Type": "application/json" },
			},
		);
	};

	useChatStore.setState({
		activeConversationId: "conversation-1",
		conversations: [
			conversation("conversation-1", "First"),
			conversation("conversation-2", "Second"),
		],
		messagesByConversationId: {
			"conversation-1": [],
			"conversation-2": [],
		},
	});

	await useChatStore.getState().sendMessage("first");
	useChatStore.setState({ activeConversationId: "conversation-2" });
	await useChatStore.getState().sendMessage("second");

	const state = useChatStore.getState();
	assert.equal(Object.keys(state.controllersByConversationId).length, 2);
	assert.notEqual(
		state.controllersByConversationId["conversation-1"],
		state.controllersByConversationId["conversation-2"],
	);
	assert.equal(
		state.controllersByConversationId["conversation-1"]?.signal.aborted,
		false,
	);
	state.controllersByConversationId["conversation-1"]?.abort();
	state.controllersByConversationId["conversation-2"]?.abort();
});

test("selectConversation unwraps backend messages envelope", async () => {
	const { useChatStore } = await loadStore();
	useChatStore.setState({
		activeConversationId: undefined,
		messagesByConversationId: {},
		runsByConversationId: {},
		controllersByConversationId: {},
	});
	globalThis.fetch = async () =>
		new Response(
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
				activeRun: null,
			}),
			{
				status: 200,
				headers: { "Content-Type": "application/json" },
			},
		);

	await useChatStore.getState().selectConversation("conversation-1");

	assert.deepEqual(useChatStore.getState().messagesByConversationId, {
		"conversation-1": [
			{
				id: "assistant-1",
				conversationId: "conversation-1",
				role: "assistant",
				content: "hello",
				status: "done",
				createdAt: "2026-01-01T00:00:00.000Z",
			},
		],
	});
});

test("selectConversation restores awaiting approval without resume request", async () => {
	const { useChatStore } = await loadStore();
	const calls: Array<{ input: string | URL | Request; init?: RequestInit }> =
		[];
	useChatStore.setState({
		activeConversationId: undefined,
		messagesByConversationId: {},
	});
	globalThis.fetch = async (input, init) => {
		calls.push({ input, init });
		const url = String(input);

		if (url.endsWith("/api/conversation/messages/conversation-1")) {
			return new Response(
				JSON.stringify({
					messages: [
						{
							id: "assistant-1",
							conversationId: "conversation-1",
							role: "assistant",
							content: "",
							status: "streaming",
							createdAt: "2026-01-01T00:00:00.000Z",
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
												toolName: "get_weather",
												args: { city: "Beijing" },
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
						status: "awaiting_approval",
						lastEventId: 42,
						assistantMessageId: "assistant-1",
						approvalBatch: {
							id: "batch-1",
							status: "pending",
							expiresAt: "2026-01-01T00:30:00.000Z",
							requests: [
								{
									id: "request-1",
									toolInvocationId: "tool-1",
									toolName: "get_weather",
									args: { city: "Beijing" },
									decision: "pending",
								},
							],
						},
					},
				}),
				{
					status: 200,
					headers: { "Content-Type": "application/json" },
				},
			);
		}

		return new Response("", { status: 500 });
	};

	await useChatStore.getState().selectConversation("conversation-1");

	assert.equal(
		calls.some((call) =>
			String(call.input).endsWith("/api/chat/stream/resume"),
		),
		false,
	);
	assert.equal(
		useChatStore.getState().runsByConversationId["conversation-1"]?.status,
		"awaiting_approval",
	);
});

test("selectConversation resumes active run from backend cursor", async () => {
	const { useChatStore } = await loadStore();
	const calls: Array<{ input: string | URL | Request; init?: RequestInit }> =
		[];
	let resolveResume:
		| ((response: Response | PromiseLike<Response>) => void)
		| undefined;
	useChatStore.setState({
		activeConversationId: undefined,
		messagesByConversationId: {},
		runsByConversationId: {},
		controllersByConversationId: {},
	});
	globalThis.fetch = async (input, init) => {
		calls.push({ input, init });
		const url = String(input);

		if (url.endsWith("/api/conversation/messages/conversation-1")) {
			return new Response(
				JSON.stringify({
					messages: [
						{
							id: "assistant-1",
							conversationId: "conversation-1",
							role: "assistant",
							content: "",
							status: "done",
							createdAt: "2026-01-01T00:00:00.000Z",
						},
					],
					activeRun: {
						runId: "run-1",
						status: "running",
						lastEventId: 42,
						assistantMessageId: "assistant-1",
						approvalBatch: null,
					},
				}),
				{
					status: 200,
					headers: { "Content-Type": "application/json" },
				},
			);
		}

		if (url.endsWith("/api/chat/stream/resume")) {
			return new Promise<Response>((resolve) => {
				resolveResume = resolve;
			});
		}

		return new Response(
			JSON.stringify([conversation("conversation-1", "Synced")]),
			{
				status: 200,
				headers: { "Content-Type": "application/json" },
			},
		);
	};

	await useChatStore.getState().selectConversation("conversation-1");
	await new Promise((resolve) => setTimeout(resolve, 0));

	const resumeCall = calls.find((call) =>
		String(call.input).endsWith("/api/chat/stream/resume"),
	);
	assert.ok(resumeCall);
	assert.equal(
		useChatStore.getState().runsByConversationId["conversation-1"]
			?.assistantMessageId,
		"assistant-1",
	);
	assert.equal(resumeCall.init?.method, "POST");
	assert.equal(
		resumeCall.init?.body,
		JSON.stringify({ runId: "run-1", afterEventId: 42 }),
	);

	assert.ok(resolveResume);
	resolveResume(
		new Response('data: {"type":"done","messageId":"assistant-1"}\n\n', {
			status: 200,
			headers: { "Content-Type": "text/event-stream" },
		}),
	);
	await new Promise((resolve) => setTimeout(resolve, 0));
});

test("selectConversation refreshes cached conversation active run before resume", async () => {
	const { useChatStore } = await loadStore();
	const calls: Array<{ input: string | URL | Request; init?: RequestInit }> =
		[];
	let resolveResume:
		| ((response: Response | PromiseLike<Response>) => void)
		| undefined;
	useChatStore.setState({
		activeConversationId: undefined,
		messagesByConversationId: {
			"conversation-1": [
				{
					id: "assistant-1",
					conversationId: "conversation-1",
					role: "assistant",
					content: "cached",
					status: "done",
					createdAt: "2026-01-01T00:00:00.000Z",
				},
			],
		},
		runsByConversationId: {},
		controllersByConversationId: {},
	});
	globalThis.fetch = async (input, init) => {
		calls.push({ input, init });
		const url = String(input);

		if (url.endsWith("/api/conversation/messages/conversation-1")) {
			return new Response(
				JSON.stringify({
					messages: [],
					activeRun: {
						runId: "run-cached",
						status: "running",
						lastEventId: 7,
						assistantMessageId: "assistant-1",
						approvalBatch: null,
					},
				}),
				{
					status: 200,
					headers: { "Content-Type": "application/json" },
				},
			);
		}

		if (url.endsWith("/api/chat/stream/resume")) {
			return new Promise<Response>((resolve) => {
				resolveResume = resolve;
			});
		}

		return new Response(
			JSON.stringify([conversation("conversation-1", "Synced")]),
			{
				status: 200,
				headers: { "Content-Type": "application/json" },
			},
		);
	};

	await useChatStore.getState().selectConversation("conversation-1");
	await new Promise((resolve) => setTimeout(resolve, 0));

	const resumeCall = calls.find((call) =>
		String(call.input).endsWith("/api/chat/stream/resume"),
	);
	assert.ok(resumeCall);
	assert.equal(
		resumeCall.init?.body,
		JSON.stringify({ runId: "run-cached", afterEventId: 7 }),
	);
	assert.equal(
		useChatStore.getState().messagesByConversationId["conversation-1"]?.[0]
			?.content,
		"cached",
	);
	assert.equal(
		useChatStore.getState().runsByConversationId["conversation-1"]?.status,
		"streaming",
	);

	assert.ok(resolveResume);
	resolveResume(
		new Response('data: {"type":"done","messageId":"assistant-1"}\n\n', {
			status: 200,
			headers: { "Content-Type": "text/event-stream" },
		}),
	);
	await new Promise((resolve) => setTimeout(resolve, 0));
});

test("selectConversation merges active server message parts with local streaming content", async () => {
	const { useChatStore } = await loadStore();
	const calls: Array<{ input: string | URL | Request; init?: RequestInit }> =
		[];
	useChatStore.setState({
		activeConversationId: undefined,
		messagesByConversationId: {
			"conversation-1": [
				{
					id: "assistant-1",
					conversationId: "conversation-1",
					role: "assistant",
					content: "local streaming content",
					status: "streaming",
					createdAt: "2026-01-01T00:00:00.000Z",
				},
			],
		},
		runsByConversationId: {},
		controllersByConversationId: {},
	});
	globalThis.fetch = async (input, init) => {
		calls.push({ input, init });
		const url = String(input);

		if (url.endsWith("/api/conversation/messages/conversation-1")) {
			return new Response(
				JSON.stringify({
					messages: [
						{
							id: "assistant-1",
							conversationId: "conversation-1",
							role: "assistant",
							content: "",
							status: "streaming",
							createdAt: "2026-01-01T00:00:00.000Z",
							timelineParts: [
								{
									id: "approval-part-1",
									type: "approval",
									orderIndex: 1,
									batch: {
										id: "batch-1",
										status: "pending",
										expiresAt: "2026-01-01T00:30:00.000Z",
										requests: [
											{
												id: "request-1",
												toolInvocationId: "tool-1",
												toolName: "get_weather",
												args: { city: "Beijing" },
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
						status: "awaiting_approval",
						lastEventId: 42,
						assistantMessageId: "assistant-1",
						approvalBatch: null,
					},
				}),
				{
					status: 200,
					headers: { "Content-Type": "application/json" },
				},
			);
		}

		if (url.endsWith("/api/chat/stream/resume")) {
			return new Response("", { status: 500 });
		}

		return new Response(
			JSON.stringify([conversation("conversation-1", "Synced")]),
			{
				status: 200,
				headers: { "Content-Type": "application/json" },
			},
		);
	};

	await useChatStore.getState().selectConversation("conversation-1");

	const mergedMessage =
		useChatStore.getState().messagesByConversationId["conversation-1"]?.[0];
	assert.equal(mergedMessage?.content, "local streaming content");
	assert.equal(mergedMessage?.timelineParts?.[0]?.type, "approval");
	if (mergedMessage?.timelineParts?.[0]?.type === "approval") {
		assert.equal(mergedMessage.timelineParts[0].batch.id, "batch-1");
	}

	assert.equal(
		calls.some((call) =>
			String(call.input).endsWith("/api/chat/stream/resume"),
		),
		false,
	);
});

test("selectConversation replaces stale cache when server has no active run", async () => {
	const { useChatStore } = await loadStore();
	useChatStore.setState({
		activeConversationId: undefined,
		messagesByConversationId: {
			"conversation-1": [
				{
					id: "assistant-stale",
					conversationId: "conversation-1",
					role: "assistant",
					content: "stale cached answer",
					status: "done",
					createdAt: "2026-01-01T00:00:00.000Z",
				},
			],
		},
		runsByConversationId: {},
		controllersByConversationId: {},
	});
	globalThis.fetch = async () =>
		new Response(
			JSON.stringify({
				messages: [
					{
						id: "assistant-fresh",
						conversationId: "conversation-1",
						role: "assistant",
						content: "fresh server answer",
						status: "done",
						createdAt: "2026-01-01T00:01:00.000Z",
					},
				],
				activeRun: null,
			}),
			{
				status: 200,
				headers: { "Content-Type": "application/json" },
			},
		);

	await useChatStore.getState().selectConversation("conversation-1");

	assert.deepEqual(
		useChatStore.getState().messagesByConversationId["conversation-1"],
		[
			{
				id: "assistant-fresh",
				conversationId: "conversation-1",
				role: "assistant",
				content: "fresh server answer",
				status: "done",
				createdAt: "2026-01-01T00:01:00.000Z",
			},
		],
	);
});

test("stream reducer handles run and approval lifecycle events", async () => {
	const { useChatStore } = await loadStore();
	globalThis.fetch = async (input) => {
		const url = String(input);

		if (url.endsWith("/api/chat/stream")) {
			return new Response(
				[
					'data: {"type":"run_created","runId":"run-1","status":"running","assistantMessageId":"assistant-1"}',
					'data: {"type":"message_created","message":{"id":"assistant-1","conversationId":"conversation-1","role":"assistant","content":"","status":"streaming","createdAt":"2026-01-01T00:00:00.000Z"}}',
					'data: {"type":"approval_required","runId":"run-1","messageId":"assistant-1","part":{"id":"approval-part-1","type":"approval","orderIndex":1,"batch":{"id":"batch-1","status":"pending","expiresAt":"2026-01-01T00:30:00.000Z","requests":[{"id":"request-1","toolInvocationId":"tool-1","toolName":"get_weather","args":{"city":"Beijing"},"decision":"pending"}]}}}',
					'data: {"type":"approval_resolved","runId":"run-1","batch":{"id":"batch-1","status":"resolved","expiresAt":"2026-01-01T00:30:00.000Z","resolutionSource":"manual","resolvedAt":"2026-01-01T00:02:00.000Z","requests":[{"id":"request-1","toolInvocationId":"tool-1","toolName":"get_weather","args":{"city":"Beijing"},"decision":"approved","decidedAt":"2026-01-01T00:02:00.000Z"}]}}',
					'data: {"type":"done","messageId":"assistant-1"}',
					"",
				].join("\n\n"),
				{
					status: 200,
					headers: { "Content-Type": "text/event-stream" },
				},
			);
		}

		return new Response(
			JSON.stringify([conversation("conversation-1", "Synced")]),
			{
				status: 200,
				headers: { "Content-Type": "application/json" },
			},
		);
	};

	useChatStore.setState({
		activeConversationId: "conversation-1",
		conversations: [conversation("conversation-1", "Local")],
		messagesByConversationId: { "conversation-1": [] },
	});

	await useChatStore.getState().sendMessage("需要天气审批");
	await new Promise((resolve) => setTimeout(resolve, 0));

	const assistant =
		useChatStore.getState().messagesByConversationId["conversation-1"]?.[1];
	assert.equal(assistant?.id, "assistant-1");
	assert.equal(assistant.status, "done");
	assert.equal(assistant.timelineParts?.[0]?.type, "approval");
	if (assistant.timelineParts?.[0]?.type === "approval") {
		assert.equal(assistant.timelineParts[0].batch.status, "resolved");
		assert.equal(
			assistant.timelineParts[0].batch.requests[0]?.decision,
			"approved",
		);
	}
});

test("sendMessage refreshes conversation messages when stream returns 409 conflict", async () => {
	const { useChatStore } = await loadStore();
	const calls: Array<{ input: string | URL | Request; init?: RequestInit }> =
		[];

	globalThis.fetch = async (input, init) => {
		calls.push({ input, init });
		const url = String(input);

		if (url.endsWith("/api/chat/stream")) {
			return new Response("conflict", { status: 409 });
		}

		if (url.endsWith("/api/conversation/messages/conversation-1")) {
			return new Response(
				JSON.stringify({
					messages: [
						{
							id: "assistant-fresh",
							conversationId: "conversation-1",
							role: "assistant",
							content: "fresh after conflict",
							status: "done",
							createdAt: "2026-01-01T00:01:00.000Z",
						},
					],
					activeRun: null,
				}),
				{
					status: 200,
					headers: { "Content-Type": "application/json" },
				},
			);
		}

		return new Response(
			JSON.stringify([conversation("conversation-1", "Synced")]),
			{
				status: 200,
				headers: { "Content-Type": "application/json" },
			},
		);
	};

	useChatStore.setState({
		activeConversationId: "conversation-1",
		conversations: [conversation("conversation-1", "Local")],
		messagesByConversationId: { "conversation-1": [] },
		runsByConversationId: {},
		controllersByConversationId: {},
	});

	await useChatStore.getState().sendMessage("hello");
	await new Promise((resolve) => setTimeout(resolve, 0));

	assert.ok(
		calls.some((call) =>
			String(call.input).endsWith("/api/conversation/messages/conversation-1"),
		),
	);
	assert.deepEqual(useChatStore.getState().messagesByConversationId, {
		"conversation-1": [
			{
				id: "assistant-fresh",
				conversationId: "conversation-1",
				role: "assistant",
				content: "fresh after conflict",
				status: "done",
				createdAt: "2026-01-01T00:01:00.000Z",
			},
		],
	});
});

test("stream reducer ignores duplicate SSE event ids in store", async () => {
	const { useChatStore } = await loadStore();
	globalThis.fetch = async (input) => {
		const url = String(input);

		if (url.endsWith("/api/chat/stream")) {
			return new Response(
				[
					'id: 40\ndata: {"type":"run_created","runId":"run-1","status":"running","assistantMessageId":"assistant-1"}',
					'id: 41\ndata: {"type":"message_created","runId":"run-1","message":{"id":"assistant-1","conversationId":"conversation-1","role":"assistant","content":"","status":"streaming","createdAt":"2026-01-01T00:00:00.000Z"}}',
					'id: 42\ndata: {"type":"delta","runId":"run-1","messageId":"assistant-1","text":"hello"}',
					'id: 42\ndata: {"type":"delta","runId":"run-1","messageId":"assistant-1","text":"hello"}',
					'id: 43\ndata: {"type":"done","runId":"run-1","messageId":"assistant-1"}',
					"",
				].join("\n\n"),
				{
					status: 200,
					headers: { "Content-Type": "text/event-stream" },
				},
			);
		}

		return new Response(
			JSON.stringify([conversation("conversation-1", "Synced")]),
			{
				status: 200,
				headers: { "Content-Type": "application/json" },
			},
		);
	};

	useChatStore.setState({
		activeConversationId: "conversation-1",
		conversations: [conversation("conversation-1", "Local")],
		messagesByConversationId: { "conversation-1": [] },
		runsByConversationId: {},
		controllersByConversationId: {},
	});

	await useChatStore.getState().sendMessage("hello");
	await new Promise((resolve) => setTimeout(resolve, 0));

	const assistant =
		useChatStore.getState().messagesByConversationId["conversation-1"]?.[1];
	assert.equal(assistant?.content, "hello");
});

test("submitApproval posts selections from run cursor and resumes stream", async () => {
	const { useChatStore } = await loadStore();
	const calls: Array<{ input: string | URL | Request; init?: RequestInit }> =
		[];
	globalThis.fetch = async (input, init) => {
		calls.push({ input, init });
		const url = String(input);

		if (url.endsWith("/api/chat/approval/decisions/batch-1")) {
			return new Response(
				[
					'id: 43\ndata: {"type":"approval_resolved","runId":"run-1","batch":{"id":"batch-1","status":"resolved","expiresAt":"2026-06-07T12:30:00.000Z","resolutionSource":"manual","resolvedAt":"2026-06-07T12:02:00.000Z","requests":[{"id":"request-1","toolInvocationId":"tool-1","toolName":"get_weather","args":{"city":"Beijing"},"decision":"approved","decidedAt":"2026-06-07T12:02:00.000Z"}]}}',
					'id: 44\ndata: {"type":"done","runId":"run-1","messageId":"assistant-1"}',
					"",
				].join("\n\n"),
				{
					status: 200,
					headers: { "Content-Type": "text/event-stream" },
				},
			);
		}

		return new Response(
			JSON.stringify([conversation("conversation-1", "Synced")]),
			{
				status: 200,
				headers: { "Content-Type": "application/json" },
			},
		);
	};

	useChatStore.setState({
		activeConversationId: "conversation-1",
		conversations: [conversation("conversation-1", "Local")],
		messagesByConversationId: {
			"conversation-1": [
				{
					id: "assistant-1",
					conversationId: "conversation-1",
					role: "assistant",
					content: "",
					status: "streaming",
					createdAt: "2026-06-07T12:00:00.000Z",
					timelineParts: [
						{
							id: "approval-part-1",
							type: "approval",
							batch: {
								id: "batch-1",
								status: "pending",
								expiresAt: "2026-06-07T12:30:00.000Z",
								requests: [
									{
										id: "request-1",
										toolInvocationId: "tool-1",
										toolName: "get_weather",
										args: { city: "Beijing" },
										decision: "pending",
									},
								],
							},
						},
					],
				},
			],
		},
		runsByConversationId: {
			"conversation-1": {
				runId: "run-1",
				assistantMessageId: "assistant-1",
				status: "awaiting_approval",
				lastEventId: 42,
			},
		},
		controllersByConversationId: {},
	});

	await useChatStore
		.getState()
		.submitApproval("batch-1", { "request-1": "approve" });

	const approvalCall = calls.find((call) =>
		String(call.input).endsWith("/api/chat/approval/decisions/batch-1"),
	);
	assert.ok(approvalCall);
	assert.equal(approvalCall.init?.method, "POST");
	assert.equal(
		approvalCall.init?.body,
		JSON.stringify({
			decisions: [{ approvalRequestId: "request-1", decision: "approve" }],
			afterEventId: 42,
		}),
	);
	assert.equal(
		useChatStore.getState().runsByConversationId["conversation-1"],
		undefined,
	);
	const approvalPart =
		useChatStore.getState().messagesByConversationId["conversation-1"]?.[0]
			?.timelineParts?.[0];
	assert.equal(approvalPart?.type, "approval");
	if (approvalPart?.type === "approval") {
		assert.equal(approvalPart.batch.status, "resolved");
		assert.equal(approvalPart.batch.requests[0]?.decision, "approved");
	}
});

test("submitApproval refreshes selected conversation when backend returns conflict", async () => {
	const { useChatStore } = await loadStore();
	const calls: Array<{ input: string | URL | Request; init?: RequestInit }> =
		[];
	globalThis.fetch = async (input, init) => {
		calls.push({ input, init });
		const url = String(input);

		if (url.endsWith("/api/chat/approval/decisions/batch-1")) {
			return new Response("conflict", { status: 409 });
		}

		if (url.endsWith("/api/conversation/messages/conversation-1")) {
			return new Response(
				JSON.stringify({
					messages: [
						{
							id: "assistant-fresh",
							conversationId: "conversation-1",
							role: "assistant",
							content: "fresh after conflict",
							status: "done",
							createdAt: "2026-06-07T12:01:00.000Z",
						},
					],
					activeRun: null,
				}),
				{
					status: 200,
					headers: { "Content-Type": "application/json" },
				},
			);
		}

		return new Response(
			JSON.stringify([conversation("conversation-1", "Synced")]),
			{
				status: 200,
				headers: { "Content-Type": "application/json" },
			},
		);
	};

	useChatStore.setState({
		activeConversationId: "conversation-1",
		conversations: [conversation("conversation-1", "Local")],
		messagesByConversationId: {
			"conversation-1": [
				{
					id: "assistant-1",
					conversationId: "conversation-1",
					role: "assistant",
					content: "",
					status: "streaming",
					createdAt: "2026-06-07T12:00:00.000Z",
					timelineParts: [
						{
							id: "approval-part-1",
							type: "approval",
							batch: {
								id: "batch-1",
								status: "pending",
								expiresAt: "2026-06-07T12:30:00.000Z",
								requests: [
									{
										id: "request-1",
										toolInvocationId: "tool-1",
										toolName: "get_weather",
										args: { city: "Beijing" },
										decision: "pending",
									},
								],
							},
						},
					],
				},
			],
		},
		runsByConversationId: {
			"conversation-1": {
				runId: "run-1",
				assistantMessageId: "assistant-1",
				status: "awaiting_approval",
				lastEventId: 42,
			},
		},
		controllersByConversationId: {},
	});

	await useChatStore
		.getState()
		.submitApproval("batch-1", { "request-1": "approve" });

	assert.ok(
		calls.some((call) =>
			String(call.input).endsWith("/api/conversation/messages/conversation-1"),
		),
	);
	assert.equal(
		useChatStore.getState().messagesByConversationId["conversation-1"]?.[0]?.id,
		"assistant-fresh",
	);
});
