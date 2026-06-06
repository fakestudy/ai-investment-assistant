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
