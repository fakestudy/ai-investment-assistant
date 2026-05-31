export const INITIAL_VISIBLE_MESSAGE_COUNT = 80;
export const VISIBLE_MESSAGE_BATCH_SIZE = 80;

type ActiveStreamingState = {
	activeConversationId?: string;
	isStreaming: boolean;
	streamingConversationId?: string;
};

type StreamableMessage = {
	id: string;
	role: string;
	status?: string;
};

type ResumableStreamingState = {
	messages: readonly StreamableMessage[];
	isStreaming: boolean;
	streamingMessageId?: string;
};

type StreamCreatedMessage = {
	content: string;
	reasoning?: string;
	toolInvocations?: unknown[];
};

type LoadedConversationMessages<T> = {
	existingMessages?: T[];
	loadedMessages: T[];
};

export function isActiveConversationStreaming({
	activeConversationId,
	isStreaming,
	streamingConversationId,
}: ActiveStreamingState): boolean {
	return Boolean(
		isStreaming &&
			activeConversationId &&
			streamingConversationId === activeConversationId,
	);
}

export function getLatestStreamingAssistantMessageId(
	messages: readonly StreamableMessage[],
): string | undefined {
	for (let index = messages.length - 1; index >= 0; index -= 1) {
		const message = messages[index];
		if (message.role === "assistant" && message.status === "streaming") {
			return message.id;
		}
	}

	return undefined;
}

export function getResumableStreamingMessageId({
	messages,
	isStreaming,
	streamingMessageId,
}: ResumableStreamingState): string | undefined {
	const latestStreamingMessageId =
		getLatestStreamingAssistantMessageId(messages);
	if (!latestStreamingMessageId) {
		return undefined;
	}

	if (isStreaming && streamingMessageId === latestStreamingMessageId) {
		return undefined;
	}

	return latestStreamingMessageId;
}

export function resetStreamCreatedMessage<T extends StreamCreatedMessage>(
	_currentMessage: T,
	replayedMessage: T,
): T {
	return replayedMessage;
}

export function resolveLoadedConversationMessages<T>({
	existingMessages,
	loadedMessages,
}: LoadedConversationMessages<T>): T[] {
	return existingMessages ?? loadedMessages;
}

export function getVisibleMessageWindow<T>(
	messages: readonly T[],
	visibleCount: number,
) {
	const safeVisibleCount = Math.max(0, Math.floor(visibleCount));
	const startIndex = Math.max(0, messages.length - safeVisibleCount);

	return {
		hiddenCount: startIndex,
		messages: messages.slice(startIndex),
		startIndex,
		totalCount: messages.length,
	};
}
