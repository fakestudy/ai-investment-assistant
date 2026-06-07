import {
	appendReasoningTimelinePart,
	resetStreamCreatedMessage,
	upsertToolTimelinePart,
} from "./chat-ui-state";
import type {
	ApprovalBatch,
	ChatMessage,
	ChatTimelinePart,
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

const upsertApprovalPart = (
	parts: ChatTimelinePart[] | undefined,
	nextPart: Extract<ChatTimelinePart, { type: "approval" }>,
) => {
	const currentParts = parts ?? [];
	const partIndex = currentParts.findIndex((part) => part.id === nextPart.id);

	if (partIndex === -1) {
		return [...currentParts, nextPart];
	}

	return currentParts.map((part, index) =>
		index === partIndex ? nextPart : part,
	);
};

const updateApprovalBatch = (
	parts: ChatTimelinePart[] | undefined,
	batch: ApprovalBatch,
) =>
	parts?.map((part) =>
		part.type === "approval" && part.batch.id === batch.id
			? { ...part, batch }
			: part,
	);

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
	parts: ChatTimelinePart[] | undefined,
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
							timelineParts: upsertApprovalPart(
								message.timelineParts,
								event.part,
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
			messages: state.messages.map((message) => ({
				...message,
				timelineParts: updateApprovalBatch(message.timelineParts, event.batch),
			})),
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
