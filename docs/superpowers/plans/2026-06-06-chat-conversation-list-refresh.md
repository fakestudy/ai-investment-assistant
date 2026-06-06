# Chat Conversation List Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Avoid duplicate conversation-list fetches caused by new-chat route changes while still forcing a list refresh after a chat stream finishes.

**Architecture:** Keep the logic inside the Zustand chat store. `loadConversations()` skips network fetches when the store already has conversations unless called with `{ force: true }`; stream completion calls the forced path to sync backend `updatedAt`, ordering, and final title.

**Tech Stack:** React 19, Next.js 16, Zustand, TypeScript, Node test runner.

---

### Task 1: Add Store-Level Fetch Guard

**Files:**
- Modify: `web/features/chat/store.ts`
- Test: `web/features/chat/store.test.ts`

- [ ] **Step 1: Write the failing test**

Create `web/features/chat/store.test.ts`:

```ts
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
	const moduleUrl = new URL(`./store.ts?test=${Date.now()}`, import.meta.url).href;
	return import(moduleUrl) as Promise<typeof import("./store")>;
}

test("loadConversations skips fetch when conversations are already loaded", async () => {
	const { useChatStore } = await loadStore();
	const calls: Array<{ input: string | URL | Request; init?: RequestInit }> = [];

	globalThis.fetch = async (input, init) => {
		calls.push({ input, init });
		return new Response(JSON.stringify([conversation("conversation-2", "Remote")]), {
			status: 200,
			headers: { "Content-Type": "application/json" },
		});
	};

	useChatStore.setState({ conversations: [conversation("conversation-1", "Local")] });

	await useChatStore.getState().loadConversations();

	assert.equal(calls.length, 0);
	assert.deepEqual(useChatStore.getState().conversations, [
		conversation("conversation-1", "Local"),
	]);
});

test("loadConversations force refreshes existing conversations", async () => {
	const { useChatStore } = await loadStore();
	const calls: Array<{ input: string | URL | Request; init?: RequestInit }> = [];

	globalThis.fetch = async (input, init) => {
		calls.push({ input, init });
		return new Response(JSON.stringify([conversation("conversation-2", "Remote")]), {
			status: 200,
			headers: { "Content-Type": "application/json" },
		});
	};

	useChatStore.setState({ conversations: [conversation("conversation-1", "Local")] });

	await useChatStore.getState().loadConversations({ force: true });

	assert.equal(calls.length, 1);
	assert.deepEqual(useChatStore.getState().conversations, [
		conversation("conversation-2", "Remote"),
	]);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd web && pnpm dlx tsx --test features/chat/store.test.ts
```

Expected: FAIL because `loadConversations` does not accept options and does not skip existing conversations.

- [ ] **Step 3: Write minimal implementation**

Update `web/features/chat/store.ts`:

```ts
type LoadConversationsOptions = {
	force?: boolean;
};

type ChatState = {
	conversations: Conversation[];
	// existing fields...
	loadConversations: (options?: LoadConversationsOptions) => Promise<void>;
	// existing actions...
};
```

Then guard inside `loadConversations`:

```ts
loadConversations: async (options) => {
	if (!options?.force && get().conversations.length > 0) {
		return;
	}

	set({ isLoadingConversations: true, error: undefined });
	// existing implementation...
},
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
cd web && pnpm dlx tsx --test features/chat/store.test.ts
```

Expected: PASS.

### Task 2: Force Refresh After Stream Finishes

**Files:**
- Modify: `web/features/chat/store.ts`
- Test: `web/features/chat/store.test.ts`

- [ ] **Step 1: Write the failing test**

Append to `web/features/chat/store.test.ts`:

```ts
test("sendMessage force refreshes conversations after stream completes", async () => {
	const { useChatStore } = await loadStore();
	const calls: Array<{ input: string | URL | Request; init?: RequestInit }> = [];

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

		return new Response(JSON.stringify([conversation("conversation-1", "Synced")]), {
			status: 200,
			headers: { "Content-Type": "application/json" },
		});
	};

	useChatStore.setState({
		activeConversationId: "conversation-1",
		conversations: [conversation("conversation-1", "Local")],
		messagesByConversationId: { "conversation-1": [] },
	});

	await useChatStore.getState().sendMessage("hello");
	await new Promise((resolve) => setTimeout(resolve, 0));

	assert.equal(
		calls.filter((call) => String(call.input).endsWith("/api/conversations/list"))
			.length,
		1,
	);
	assert.equal(useChatStore.getState().conversations[0]?.title, "Synced");
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd web && pnpm dlx tsx --test features/chat/store.test.ts
```

Expected: FAIL because stream completion does not force refresh conversations.

- [ ] **Step 3: Write minimal implementation**

Update `startStream` in `web/features/chat/store.ts` after `await input.connect(...)`:

```ts
await get().loadConversations({ force: true });
```

Keep this after the stream promise resolves, not inside every `done` event reducer, so the list refresh runs once per completed stream.

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
cd web && pnpm dlx tsx --test features/chat/store.test.ts
```

Expected: PASS.

### Task 3: Verify Frontend Quality Gate

**Files:**
- Verify: `web/features/chat/store.ts`
- Verify: `web/features/chat/store.test.ts`

- [ ] **Step 1: Run formatter/linter check**

Run:

```bash
cd web && pnpm lint
```

Expected: PASS.

- [ ] **Step 2: Run focused tests**

Run:

```bash
cd web && pnpm dlx tsx --test features/chat/store.test.ts features/chat/api.test.ts
```

Expected: PASS.
