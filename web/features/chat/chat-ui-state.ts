export const INITIAL_VISIBLE_MESSAGE_COUNT = 80;
export const VISIBLE_MESSAGE_BATCH_SIZE = 80;

type ActiveStreamingState = {
	activeConversationId?: string;
	isStreaming: boolean;
	streamingConversationId?: string;
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
