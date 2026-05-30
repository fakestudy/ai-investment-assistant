"use client";

import {
	Conversation,
	ConversationContent,
	ConversationEmptyState,
	ConversationScrollButton,
} from "@/components/ai-elements/conversation";
import { useChatStore } from "../store";
import { ChatMessageItem } from "./chat-message-item";

export function ChatMessageList() {
	const activeConversationId = useChatStore(
		(state) => state.activeConversationId,
	);
	const messages = useChatStore((state) =>
		activeConversationId
			? (state.messagesByConversationId[activeConversationId] ?? [])
			: [],
	);
	const isLoadingMessages = useChatStore((state) => state.isLoadingMessages);
	const editUserMessageAndRegenerate = useChatStore(
		(state) => state.editUserMessageAndRegenerate,
	);
	const regenerateLastAssistantMessage = useChatStore(
		(state) => state.regenerateLastAssistantMessage,
	);

	if (isLoadingMessages) {
		return (
			<div className="flex flex-1 items-center justify-center px-6 text-zinc-500 text-sm">
				Loading messages...
			</div>
		);
	}

	if (messages.length === 0) {
		return (
			<ConversationEmptyState className="flex-1">
				<p className="font-semibold text-3xl text-zinc-900 tracking-tight">
					How can I help?
				</p>
			</ConversationEmptyState>
		);
	}

	return (
		<Conversation className="bg-white">
			<ConversationContent className="mx-auto w-full max-w-3xl gap-7 px-6 py-8">
				{messages.map((message, index) => {
					const isLastAssistantMessage =
						message.role === "assistant" && index === messages.length - 1;

					return (
						<ChatMessageItem
							canRegenerate={isLastAssistantMessage}
							key={message.id}
							message={message}
							onEditUserMessage={editUserMessageAndRegenerate}
							onRegenerate={regenerateLastAssistantMessage}
						/>
					);
				})}
			</ConversationContent>
			<ConversationScrollButton className="border-zinc-200 bg-white shadow-sm" />
		</Conversation>
	);
}
