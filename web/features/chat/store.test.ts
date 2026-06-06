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

async function loadStore() {
	const moduleUrl = new URL(`./store.ts?test=${Date.now()}`, import.meta.url)
		.href;
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
