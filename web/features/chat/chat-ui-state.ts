export const INITIAL_VISIBLE_MESSAGE_COUNT = 80;
export const VISIBLE_MESSAGE_BATCH_SIZE = 80;

import type { ChatTimelinePart, ToolInvocation } from "./types";

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
	timelineParts?: unknown[];
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

export function appendReasoningTimelinePart(
	parts: readonly ChatTimelinePart[] | undefined,
	input: { id: string; text: string },
): ChatTimelinePart[] {
	const currentParts = parts ?? [];
	const lastPart = currentParts.at(-1);

	if (lastPart?.type === "reasoning") {
		return currentParts.map((part, index) =>
			index === currentParts.length - 1 && part.type === "reasoning"
				? { ...part, text: `${part.text}${input.text}` }
				: part,
		);
	}

	return [
		...currentParts,
		{
			id: input.id,
			type: "reasoning",
			text: input.text,
		},
	];
}

export function upsertToolTimelinePart(
	parts: readonly ChatTimelinePart[] | undefined,
	invocation: ToolInvocation,
): ChatTimelinePart[] {
	const currentParts = parts ?? [];
	const existingIndex = currentParts.findIndex(
		(part) => part.type === "tool" && part.invocation.id === invocation.id,
	);

	if (existingIndex === -1) {
		return [
			...currentParts,
			{
				id: invocation.id,
				type: "tool",
				invocation,
			},
		];
	}

	return currentParts.map((part, index) =>
		index === existingIndex && part.type === "tool"
			? { ...part, invocation: { ...part.invocation, ...invocation } }
			: part,
	);
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
