"use client";

import { useChatStore } from "../store";

export function ChatSidebar() {
	const createNewConversation = useChatStore(
		(state) => state.createNewConversation,
	);
	const isLoadingConversations = useChatStore(
		(state) => state.isLoadingConversations,
	);

	return (
		<aside className="flex w-[260px] shrink-0 flex-col border-zinc-200 border-r bg-zinc-50 p-3">
			<button
				className="flex h-10 w-full items-center justify-center rounded-lg border border-zinc-200 bg-white px-3 font-medium text-sm text-zinc-900 shadow-sm transition-colors hover:bg-zinc-100 disabled:cursor-not-allowed disabled:opacity-60"
				disabled={isLoadingConversations}
				onClick={() => {
					void createNewConversation();
				}}
				type="button"
			>
				New chat
			</button>
		</aside>
	);
}
