"use client";

import { useEffect } from "react";
import { useChatStore } from "../store";
import { ChatMain } from "./chat-main";
import { ChatSidebar } from "./chat-sidebar";

export function ChatShell() {
	const loadConversations = useChatStore((state) => state.loadConversations);

	useEffect(() => {
		void loadConversations();
	}, [loadConversations]);

	return (
		<div className="flex h-screen bg-[linear-gradient(180deg,#fafafa_0%,#ffffff_42%)] text-zinc-950">
			<ChatSidebar />
			<ChatMain />
		</div>
	);
}
