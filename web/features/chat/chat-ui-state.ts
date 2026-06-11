export const INITIAL_VISIBLE_MESSAGE_COUNT = 80;
export const VISIBLE_MESSAGE_BATCH_SIZE = 80;

import type {
	ApprovalBatch,
	ApprovalRequest,
	ChatTimelinePart,
	RunTimelineItem,
	ToolApprovalState,
	ToolInvocation,
	ToolInvocationStatus,
} from "./types";

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

type ConversationInputLockState = {
	runsByConversationId: Record<
		string,
		{ status: "streaming" | "awaiting_approval" | "resuming" } | undefined
	>;
};

type PendingApprovalInputState = {
	activeConversationId?: string;
	runsByConversationId: Record<
		string,
		| {
				status: "streaming" | "awaiting_approval" | "resuming";
				approvalBatch?: ApprovalBatch;
		  }
		| undefined
	>;
};

type StreamCreatedMessage = {
	content: string;
	reasoning?: string;
	toolInvocations?: unknown[];
	timelineParts?: unknown[];
	timelineItems?: unknown[];
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

export function isConversationInputLocked(
	state: ConversationInputLockState,
	conversationId: string | undefined,
): boolean {
	if (!conversationId) {
		return false;
	}

	const run = state.runsByConversationId[conversationId];
	return (
		run?.status === "streaming" ||
		run?.status === "awaiting_approval" ||
		run?.status === "resuming"
	);
}

export function getPendingApprovalForInput(
	state: PendingApprovalInputState,
): ApprovalBatch | undefined {
	const { activeConversationId } = state;
	if (!activeConversationId) {
		return undefined;
	}

	const run = state.runsByConversationId[activeConversationId];
	if (
		run?.status !== "awaiting_approval" ||
		run.approvalBatch?.status !== "pending"
	) {
		return undefined;
	}

	return run.approvalBatch;
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

export function appendThoughtTimelineItem(
	items: readonly RunTimelineItem[] | undefined,
	input: { id: string; text: string },
): RunTimelineItem[] {
	const currentItems = items ?? [];
	const lastItem = currentItems.at(-1);

	if (lastItem?.type === "thought") {
		return currentItems.map((item, index) =>
			index === currentItems.length - 1 && item.type === "thought"
				? { ...item, text: `${item.text}${input.text}` }
				: item,
		);
	}

	return [
		...currentItems,
		{
			id: input.id,
			type: "thought",
			text: input.text,
		},
	];
}

export function upsertToolTimelineItem(
	items: readonly RunTimelineItem[] | undefined,
	invocation: ToolInvocation,
): RunTimelineItem[] {
	const currentItems = items ?? [];
	const existingIndex = currentItems.findIndex(
		(item) => item.type === "tool" && item.invocation.id === invocation.id,
	);

	if (existingIndex === -1) {
		return [
			...currentItems,
			{
				id: invocation.id,
				type: "tool",
				invocation,
			},
		];
	}

	return currentItems.map((item, index) =>
		index === existingIndex && item.type === "tool"
			? { ...item, invocation: { ...item.invocation, ...invocation } }
			: item,
	);
}

function toolStatusFromApprovalRequest(
	request: ApprovalRequest,
	batch: ApprovalBatch,
): ToolInvocationStatus {
	if (request.decision === "approved") {
		return "running";
	}
	if (request.decision === "rejected") {
		return "rejected";
	}
	if (request.decision === "expired" || batch.status === "expired") {
		return "expired";
	}
	return "awaiting_approval";
}

function toToolApprovalState(
	batch: ApprovalBatch,
	request: ApprovalRequest,
): ToolApprovalState {
	return {
		batchId: batch.id,
		requestId: request.id,
		status: batch.status,
		decision: request.decision,
		expiresAt: batch.expiresAt,
		decidedAt: request.decidedAt,
	};
}

function toApprovalInvocation(
	batch: ApprovalBatch,
	request: ApprovalRequest,
	messageId: string,
): ToolInvocation {
	return {
		id: request.toolInvocationId,
		messageId,
		toolName: request.toolName,
		args: request.args,
		status: toolStatusFromApprovalRequest(request, batch),
	};
}

function mergeToolStatusWithApproval(
	currentStatus: ToolInvocationStatus,
	batch: ApprovalBatch,
	request: ApprovalRequest,
): ToolInvocationStatus {
	if (currentStatus === "completed" || currentStatus === "error") {
		return currentStatus;
	}

	return toolStatusFromApprovalRequest(request, batch);
}

export function upsertApprovalBatchIntoTimelineItems(
	items: readonly RunTimelineItem[] | undefined,
	batch: ApprovalBatch,
	options: { messageId: string; orderIndex?: number },
): RunTimelineItem[] {
	let nextItems = [...(items ?? [])];

	for (const request of batch.requests) {
		const itemIndex = nextItems.findIndex(
			(item) =>
				item.type === "tool" && item.invocation.id === request.toolInvocationId,
		);
		const approval = toToolApprovalState(batch, request);

		if (itemIndex === -1) {
			nextItems = [
				...nextItems,
				{
					id: `approval-tool-${request.toolInvocationId}`,
					type: "tool",
					orderIndex: options.orderIndex,
					invocation: toApprovalInvocation(batch, request, options.messageId),
					approval,
				},
			];
			continue;
		}

		nextItems = nextItems.map((item, index) =>
			index === itemIndex && item.type === "tool"
				? {
						...item,
						invocation: {
							...item.invocation,
							status: mergeToolStatusWithApproval(
								item.invocation.status,
								batch,
								request,
							),
						},
						approval,
					}
				: item,
		);
	}

	return nextItems;
}

export function getRenderableTimelineItems(
	items: readonly RunTimelineItem[] | undefined,
): RunTimelineItem[] {
	return [...(items ?? [])].sort(
		(first, second) => (first.orderIndex ?? 0) - (second.orderIndex ?? 0),
	);
}

export function getRenderableTimelineParts(
	parts: readonly ChatTimelinePart[] | undefined,
): ChatTimelinePart[] {
	return [...(parts ?? [])].sort(
		(first, second) => (first.orderIndex ?? 0) - (second.orderIndex ?? 0),
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
