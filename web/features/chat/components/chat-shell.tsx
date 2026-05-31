"use client";

import { useEffect } from "react";
import { useChatStore } from "../store";
import { ChatErrorToast } from "./chat-error-toast";
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
			<ChatErrorToast />
			<ChatSidebar />
			<ChatMain />
		</div>
	);
}
