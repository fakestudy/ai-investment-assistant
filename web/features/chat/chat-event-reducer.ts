import {
	appendReasoningTimelinePart,
	appendThoughtTimelineItem,
	resetStreamCreatedMessage,
	upsertApprovalBatchIntoTimelineItems,
	upsertToolTimelineItem,
	upsertToolTimelinePart,
} from "./chat-ui-state";
import type {
	ChatMessage,
	ConversationRunState,
	ReceivedChatStreamEvent,
	ToolInvocation,
} from "./types";

export type ChatEventReducerState = {
	messages: ChatMessage[];
	activeRun?: ConversationRunState;
};

const withCursor = (
	activeRun: ConversationRunState | undefined,
	eventId: number | undefined,
) =>
	activeRun && eventId !== undefined
		? { ...activeRun, lastEventId: eventId }
		: activeRun;

const appendText = (
	messages: ChatMessage[],
	messageId: string,
	text: string,
	field: "content" | "reasoning",
) =>
	messages.map((message) =>
		message.id === messageId
			? {
					...message,
					[field]: `${message[field] ?? ""}${text}`,
					status: "streaming" as const,
				}
			: message,
	);

const upsertMessage = (
	messages: ChatMessage[],
	nextMessage: ChatMessage,
): ChatMessage[] => {
	const messageIndex = messages.findIndex(
		(message) => message.id === nextMessage.id,
	);

	if (messageIndex === -1) {
		return [...messages, nextMessage];
	}

	return messages.map((message, index) =>
		index === messageIndex
			? resetStreamCreatedMessage(message, nextMessage)
			: message,
	);
};

const updateMessage = (
	messages: ChatMessage[],
	messageId: string,
	update: (message: ChatMessage) => ChatMessage,
): ChatMessage[] =>
	messages.map((message) =>
		message.id === messageId ? update(message) : message,
	);

const upsertToolInvocation = (
	invocations: ToolInvocation[] | undefined,
	nextInvocation: ToolInvocation,
): ToolInvocation[] => {
	const currentInvocations = invocations ?? [];
	const invocationIndex = currentInvocations.findIndex(
		(invocation) => invocation.id === nextInvocation.id,
	);

	if (invocationIndex === -1) {
		return [...currentInvocations, nextInvocation];
	}

	return currentInvocations.map((invocation, index) =>
		index === invocationIndex
			? { ...invocation, ...nextInvocation }
			: invocation,
	);
};

const createReasoningPartId = (
	messageId: string,
	eventId: number | undefined,
	parts: readonly unknown[] | undefined,
) => `reasoning-${eventId ?? `${messageId}-${parts?.length ?? 0}`}`;

export function reduceChatStreamEvent(
	state: ChatEventReducerState,
	received: ReceivedChatStreamEvent,
): ChatEventReducerState {
	const { event, eventId } = received;

	if (
		eventId !== undefined &&
		state.activeRun?.lastEventId !== undefined &&
		eventId <= state.activeRun.lastEventId
	) {
		return state;
	}

	if (event.type === "run_created") {
		return {
			...state,
			activeRun: {
				runId: event.runId,
				assistantMessageId: event.assistantMessageId,
				status: "streaming",
				lastEventId: eventId,
			},
		};
	}

	if (event.type === "message_created") {
		return {
			...state,
			messages: upsertMessage(state.messages, event.message),
			activeRun: withCursor(state.activeRun, eventId),
		};
	}

	if (event.type === "delta") {
		return {
			...state,
			messages: appendText(
				state.messages,
				event.messageId,
				event.text,
				"content",
			),
			activeRun: withCursor(state.activeRun, eventId),
		};
	}

	if (event.type === "reasoning") {
		return {
			...state,
			messages: updateMessage(state.messages, event.messageId, (message) => ({
				...message,
				reasoning: `${message.reasoning ?? ""}${event.text}`,
				timelineParts: appendReasoningTimelinePart(message.timelineParts, {
					id: createReasoningPartId(
						event.messageId,
						eventId,
						message.timelineParts,
					),
					text: event.text,
				}),
				timelineItems: appendThoughtTimelineItem(message.timelineItems, {
					id: createReasoningPartId(
						event.messageId,
						eventId,
						message.timelineItems,
					),
					text: event.text,
				}),
				status: "streaming",
			})),
			activeRun: withCursor(state.activeRun, eventId),
		};
	}

	if (event.type === "tool_call" || event.type === "tool_result") {
		return {
			...state,
			messages: updateMessage(state.messages, event.messageId, (message) => ({
				...message,
				toolInvocations: upsertToolInvocation(
					message.toolInvocations,
					event.invocation,
				),
				timelineParts: upsertToolTimelinePart(
					message.timelineParts,
					event.invocation,
				),
				timelineItems: upsertToolTimelineItem(
					message.timelineItems,
					event.invocation,
				),
				status: "streaming",
			})),
			activeRun: withCursor(state.activeRun, eventId),
		};
	}

	if (event.type === "approval_required") {
		return {
			...state,
			messages: state.messages.map((message) =>
				message.id === event.messageId
					? {
							...message,
							timelineItems: upsertApprovalBatchIntoTimelineItems(
								message.timelineItems,
								event.part.batch,
								{
									messageId: event.messageId,
									orderIndex: event.part.orderIndex,
								},
							),
							status: "streaming",
						}
					: message,
			),
			activeRun: {
				runId: event.runId,
				assistantMessageId:
					state.activeRun?.assistantMessageId ?? event.messageId,
				status: "awaiting_approval",
				lastEventId: eventId,
				approvalBatch: event.part.batch,
			},
		};
	}

	if (event.type === "approval_resolved") {
		return {
			...state,
			messages: state.messages.map((message) =>
				message.id ===
				(state.activeRun?.assistantMessageId ?? state.messages[0]?.id ?? "")
					? {
							...message,
							timelineItems: upsertApprovalBatchIntoTimelineItems(
								message.timelineItems,
								event.batch,
								{ messageId: message.id },
							),
						}
					: message,
			),
			activeRun: {
				runId: event.runId,
				assistantMessageId:
					state.activeRun?.assistantMessageId ?? state.messages[0]?.id ?? "",
				status: "resuming",
				lastEventId: eventId,
				approvalBatch: event.batch,
			},
		};
	}

	if (event.type === "done") {
		return {
			...state,
			messages: state.messages.map((message) =>
				message.id === event.messageId
					? { ...message, status: "done" }
					: message,
			),
			activeRun: undefined,
		};
	}

	if (event.type === "error") {
		return {
			...state,
			messages: event.messageId
				? state.messages.map((message) =>
						message.id === event.messageId
							? { ...message, status: "error" }
							: message,
					)
				: state.messages,
			activeRun: undefined,
		};
	}

	return {
		...state,
		activeRun: withCursor(state.activeRun, eventId),
	};
}
