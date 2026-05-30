# Chat Route Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move empty new chats to `/chat`, historical chats to `/chat/{conversationId}`, and keep the new chat button idle when already on an unsent empty chat.

**Architecture:** Add App Router pages that pass an optional conversation id into the existing `ChatShell`. `ChatShell` synchronizes the route into the Zustand chat store, while `ChatSidebar` uses Next navigation and `sendMessage` lazily creates a conversation before replacing the URL.

**Tech Stack:** Next.js 16 App Router, React 19, Zustand, TypeScript, Biome.

---

### Task 1: Route Entries

**Files:**
- Create: `web/app/chat/page.tsx`
- Create: `web/app/chat/[conversationId]/page.tsx`
- Modify: `web/app/page.tsx`

- [ ] **Step 1: Add `/chat` page**

```tsx
import { ChatShell } from "@/features/chat/components/chat-shell";

export default function ChatPage() {
	return <ChatShell />;
}
```

- [ ] **Step 2: Add `/chat/[conversationId]` page**

```tsx
import { ChatShell } from "@/features/chat/components/chat-shell";

type ChatConversationPageProps = {
	params: Promise<{
		conversationId: string;
	}>;
};

export default async function ChatConversationPage({
	params,
}: ChatConversationPageProps) {
	const { conversationId } = await params;

	return <ChatShell conversationId={conversationId} />;
}
```

- [ ] **Step 3: Redirect root to `/chat`**

```tsx
import { redirect } from "next/navigation";

export default function Home() {
	redirect("/chat");
}
```

- [ ] **Step 4: Run route type check**

Run: `pnpm lint`

Expected: Biome check passes or reports only pre-existing unrelated issues.

### Task 2: Store Route Synchronization

**Files:**
- Modify: `web/features/chat/store.ts`

- [ ] **Step 1: Add `clearActiveConversation` to the state type**

```ts
type ChatState = {
	conversations: Conversation[];
	activeConversationId?: string;
	messagesByConversationId: Record<string, ChatMessage[]>;
	isLoadingConversations: boolean;
	isLoadingMessages: boolean;
	isStreaming: boolean;
	streamingConversationId?: string;
	error?: ChatError;
	abortController?: AbortController;
	loadConversations: () => Promise<void>;
	createNewConversation: () => Promise<void>;
	clearActiveConversation: () => void;
	selectConversation: (conversationId: string) => Promise<void>;
	renameActiveConversation: (title: string) => Promise<void>;
	deleteActiveConversation: () => Promise<void>;
	sendMessage: (content: string) => Promise<void>;
	stopStreaming: () => void;
	regenerateLastAssistantMessage: () => Promise<void>;
	editUserMessageAndRegenerate: (
		messageId: string,
		content: string,
	) => Promise<void>;
	clearError: () => void;
};
```

- [ ] **Step 2: Stop auto-selecting the first conversation on load**

```ts
loadConversations: async () => {
	set({ isLoadingConversations: true, error: undefined });

	try {
		const conversations = await listConversations();
		const activeConversationId =
			get().activeConversationId &&
			conversations.some(
				(conversation) => conversation.id === get().activeConversationId,
			)
				? get().activeConversationId
				: undefined;

		set({
			conversations,
			activeConversationId,
			isLoadingConversations: false,
		});

		if (activeConversationId) {
			await get().selectConversation(activeConversationId);
		}
	} catch (error) {
		set({
			isLoadingConversations: false,
			error: toChatError(error, "conversation"),
		});
	}
},
```

- [ ] **Step 3: Add clear action implementation**

```ts
clearActiveConversation: () => {
	set({ activeConversationId: undefined, error: undefined });
},
```

- [ ] **Step 4: Keep existing lazy creation in `sendMessage`**

Confirm `sendMessage` still creates a conversation only when `activeConversationId` is empty.

Run: `pnpm lint`

Expected: no TypeScript or Biome errors from the new store method.

### Task 3: Shell URL Sync

**Files:**
- Modify: `web/features/chat/components/chat-shell.tsx`

- [ ] **Step 1: Accept route conversation id**

```tsx
"use client";

import { useEffect } from "react";
import { useChatStore } from "../store";
import { ChatMain } from "./chat-main";
import { ChatSidebar } from "./chat-sidebar";

type ChatShellProps = {
	conversationId?: string;
};

export function ChatShell({ conversationId }: ChatShellProps) {
	const clearActiveConversation = useChatStore(
		(state) => state.clearActiveConversation,
	);
	const loadConversations = useChatStore((state) => state.loadConversations);
	const selectConversation = useChatStore((state) => state.selectConversation);

	useEffect(() => {
		void loadConversations();
	}, [loadConversations]);

	useEffect(() => {
		if (conversationId) {
			void selectConversation(conversationId);
			return;
		}

		clearActiveConversation();
	}, [clearActiveConversation, conversationId, selectConversation]);

	return (
		<div className="flex h-screen bg-[linear-gradient(180deg,#fafafa_0%,#ffffff_42%)] text-zinc-950">
			<ChatSidebar />
			<ChatMain />
		</div>
	);
}
```

- [ ] **Step 2: Verify direct URL selection**

Run: `pnpm lint`

Expected: no hook dependency warnings or type errors.

### Task 4: Sidebar Navigation

**Files:**
- Modify: `web/features/chat/components/chat-sidebar.tsx`

- [ ] **Step 1: Import router and pathname hooks**

```tsx
import {
	MessageSquareIcon,
	PencilIcon,
	PlusIcon,
	Trash2Icon,
} from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";
```

- [ ] **Step 2: Replace create action with navigation-aware new chat**

```tsx
const activeConversationId = useChatStore(
	(state) => state.activeConversationId,
);
const clearActiveConversation = useChatStore(
	(state) => state.clearActiveConversation,
);
const router = useRouter();
const pathname = usePathname();
```

```tsx
onClick={() => {
	if (pathname === "/chat" && !activeConversationId) {
		return;
	}

	clearActiveConversation();
	router.push("/chat");
}}
```

- [ ] **Step 3: Navigate when selecting history**

```tsx
onSelect={() => {
	router.push(`/chat/${encodeURIComponent(conversation.id)}`);
}}
```

- [ ] **Step 4: Remove unused `createNewConversation` and `selectConversation` bindings**

Run: `pnpm lint`

Expected: no unused variable errors.

### Task 5: First Message URL Replacement

**Files:**
- Modify: `web/features/chat/components/chat-input.tsx`
- Modify: `web/features/chat/store.ts`

- [ ] **Step 1: Return the active conversation id from `sendMessage` immediately after starting the stream**

```ts
sendMessage: (content: string) => Promise<string | undefined>;
```

At the end of `sendMessage`, start the stream without awaiting it, then return `conversationId` so the caller can replace the URL immediately after the backend conversation is created.

```ts
void startStream({ conversationId, message }, set, get);
return conversationId;
```

- [ ] **Step 2: Update empty/invalid returns**

```ts
if (!message) {
	return undefined;
}
```

```ts
set({ error: toChatError(error, "conversation") });
return undefined;
```

- [ ] **Step 3: Replace URL from input submit when needed**

Use `usePathname` and `useRouter` in `chat-input.tsx`. After `sendMessage(value)` resolves, if the current pathname is `/chat` and a conversation id is returned, call `router.replace(`/chat/${encodeURIComponent(conversationId)}`)`.

- [ ] **Step 4: Run linter**

Run: `pnpm lint`

Expected: no type errors from the changed `sendMessage` signature.

### Task 6: Final Verification

**Files:**
- Verify: `web/app/chat/page.tsx`
- Verify: `web/app/chat/[conversationId]/page.tsx`
- Verify: `web/features/chat/components/chat-shell.tsx`
- Verify: `web/features/chat/components/chat-sidebar.tsx`
- Verify: `web/features/chat/components/chat-input.tsx`
- Verify: `web/features/chat/store.ts`

- [ ] **Step 1: Run frontend lint**

Run: `pnpm lint`

Expected: Biome check passes.

- [ ] **Step 2: Run frontend build**

Run: `pnpm build`

Expected: Next build succeeds and route type generation accepts `/chat/[conversationId]`.

- [ ] **Step 3: Manual smoke test**

Run: `pnpm dev`

Expected:
- Opening `/chat` shows an empty chat.
- New chat on `/chat` with no active conversation does nothing.
- Selecting a history item navigates to `/chat/{conversationId}`.
- New chat on `/chat/{conversationId}` navigates to `/chat`.
- Sending the first message on `/chat` creates a conversation and replaces the URL with `/chat/{conversationId}`.

## Self-Review

- Spec coverage: the plan covers `/chat`, `/chat/{conversationId}`, lazy conversation creation, immediate URL replacement after conversation creation, no-op new chat behavior, history navigation, and verification.
- Placeholder scan: no TBD or unresolved implementation placeholders remain.
- Type consistency: `clearActiveConversation` and `sendMessage` signature changes are introduced before consumers use them.
