"use client";

import { useEffect, useMemo, useState } from "react";
import {
	Conversation,
	ConversationContent,
	ConversationEmptyState,
	ConversationScrollButton,
} from "@/components/ai-elements/conversation";
import { Button } from "@/components/ui/button";
import {
	getVisibleMessageWindow,
	INITIAL_VISIBLE_MESSAGE_COUNT,
	VISIBLE_MESSAGE_BATCH_SIZE,
} from "../chat-ui-state";
import { useChatStore } from "../store";
import type { ChatMessage } from "../types";
import { ChatMessageItem } from "./chat-message-item";

const EMPTY_MESSAGES: ChatMessage[] = [];

export function ChatMessageList() {
	const activeConversationId = useChatStore(
		(state) => state.activeConversationId,
	);
	const messages = useChatStore((state) =>
		activeConversationId
			? (state.messagesByConversationId[activeConversationId] ?? EMPTY_MESSAGES)
			: EMPTY_MESSAGES,
	);
	const isLoadingMessages = useChatStore((state) => state.isLoadingMessages);
	const editUserMessageAndRegenerate = useChatStore(
		(state) => state.editUserMessageAndRegenerate,
	);
	const regenerateLastAssistantMessage = useChatStore(
		(state) => state.regenerateLastAssistantMessage,
	);
	const [messageWindow, setMessageWindow] = useState<{
		conversationId?: string;
		visibleCount: number;
	}>({
		conversationId: activeConversationId,
		visibleCount: INITIAL_VISIBLE_MESSAGE_COUNT,
	});
	const visibleMessageCount =
		messageWindow.conversationId === activeConversationId
			? messageWindow.visibleCount
			: INITIAL_VISIBLE_MESSAGE_COUNT;
	const {
		hiddenCount,
		messages: visibleMessages,
		startIndex,
	} = useMemo(
		() => getVisibleMessageWindow(messages, visibleMessageCount),
		[messages, visibleMessageCount],
	);
	const earlierMessageCount = Math.min(
		hiddenCount,
		VISIBLE_MESSAGE_BATCH_SIZE,
	);

	useEffect(() => {
		setMessageWindow({
			conversationId: activeConversationId,
			visibleCount: INITIAL_VISIBLE_MESSAGE_COUNT,
		});
	}, [activeConversationId]);

	const showEarlierMessages = () => {
		setMessageWindow((currentWindow) => {
			const currentVisibleCount =
				currentWindow.conversationId === activeConversationId
					? currentWindow.visibleCount
					: INITIAL_VISIBLE_MESSAGE_COUNT;

			return {
				conversationId: activeConversationId,
				visibleCount: Math.min(
					messages.length,
					currentVisibleCount + VISIBLE_MESSAGE_BATCH_SIZE,
				),
			};
		});
	};

	if (isLoadingMessages) {
		return (
			<div
				aria-live="polite"
				className="flex flex-1 items-center justify-center px-6 text-zinc-500 text-sm"
			>
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
			<ConversationContent className="mx-auto w-full max-w-6xl gap-7 px-6 py-8">
				{hiddenCount > 0 && (
					<div className="flex justify-center">
						<Button
							className="border-zinc-200 bg-white text-zinc-700 shadow-sm"
							onClick={showEarlierMessages}
							size="sm"
							type="button"
							variant="outline"
						>
							Show {earlierMessageCount} earlier{" "}
							{earlierMessageCount === 1 ? "message" : "messages"}
						</Button>
					</div>
				)}
				{visibleMessages.map((message, index) => {
					const isLastAssistantMessage =
						message.role === "assistant" &&
						startIndex + index === messages.length - 1;

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
