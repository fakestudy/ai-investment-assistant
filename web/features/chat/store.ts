import { create } from "zustand";
import {
	ChatApiError,
	cancelChatStream,
	createConversation,
	deleteConversation,
	editMessage,
	listConversations,
	listMessages,
	renameConversation,
	resumeChatStream,
	streamChat,
	submitApprovalDecisions,
} from "./api";
import { reduceChatStreamEvent } from "./chat-event-reducer";
import type { ApprovalSelections } from "./components/approval-card-state";
import type {
	ActiveRunSummary,
	ApprovalBatch,
	ChatError,
	ChatMessage,
	ChatStreamEvent,
	Conversation,
	ConversationRunState,
	ReceivedChatStreamEvent,
} from "./types";

type LoadConversationsOptions = {
	force?: boolean;
};

type SelectConversationOptions = {
	force?: boolean;
};

type ChatState = {
	conversations: Conversation[];
	activeConversationId?: string;
	messagesByConversationId: Record<string, ChatMessage[]>;
	runsByConversationId: Record<string, ConversationRunState | undefined>;
	controllersByConversationId: Record<string, AbortController | undefined>;
	isLoadingConversations: boolean;
	isLoadingMessages: boolean;
	error?: ChatError;
	loadConversations: (options?: LoadConversationsOptions) => Promise<void>;
	createNewConversation: () => Promise<void>;
	clearActiveConversation: () => void;
	selectConversation: (
		conversationId: string,
		options?: SelectConversationOptions,
	) => Promise<void>;
	renameActiveConversation: (title: string) => Promise<void>;
	deleteActiveConversation: () => Promise<{
		deleted: boolean;
		nextConversationId?: string;
	}>;
	sendMessage: (content: string) => Promise<string | undefined>;
	submitApproval: (
		batchId: string,
		selections: ApprovalSelections,
	) => Promise<void>;
	stopStreaming: () => void;
	regenerateLastAssistantMessage: () => Promise<void>;
	editUserMessageAndRegenerate: (
		messageId: string,
		previousContent: string,
		nextContent: string,
	) => Promise<void>;
	clearError: () => void;
};

const createLocalId = () => {
	if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
		return crypto.randomUUID();
	}

	return `local-${Date.now()}-${Math.random().toString(36).slice(2)}`;
};

const toChatError = (error: unknown, scope: ChatError["scope"]): ChatError => ({
	message: error instanceof Error ? error.message : "Unexpected chat error",
	scope,
});

const updateMessage = (
	messages: ChatMessage[],
	messageId: string,
	update: (message: ChatMessage) => ChatMessage,
): ChatMessage[] =>
	messages.map((message) =>
		message.id === messageId ? update(message) : message,
	);

const updateConversationTitle = (
	conversations: Conversation[],
	conversationId: string,
	title: string,
): Conversation[] =>
	conversations.map((conversation) =>
		conversation.id === conversationId
			? { ...conversation, title }
			: conversation,
	);

const appendOptimisticUserMessage = (
	messages: ChatMessage[],
	conversationId: string,
	content: string,
): ChatMessage[] => [
	...messages,
	{
		id: createLocalId(),
		conversationId,
		role: "user",
		content,
		status: "done",
		createdAt: new Date().toISOString(),
	},
];

const resetAssistantMessageForRegeneration = (
	message: ChatMessage,
): ChatMessage => ({
	...message,
	content: "",
	reasoning: undefined,
	toolInvocations: undefined,
	timelineParts: undefined,
	status: "streaming",
});

const mergeTimelinePartsById = (
	loadedParts: ChatMessage["timelineParts"],
	existingParts: ChatMessage["timelineParts"],
) => {
	if (!loadedParts?.length) {
		return existingParts;
	}

	if (!existingParts?.length) {
		return loadedParts;
	}

	const loadedPartIds = new Set(loadedParts.map((part) => part.id));
	return [
		...loadedParts,
		...existingParts.filter((part) => !loadedPartIds.has(part.id)),
	];
};

const mergeLoadedConversationMessagesById = ({
	existingMessages,
	loadedMessages,
}: {
	existingMessages: ChatMessage[] | undefined;
	loadedMessages: ChatMessage[];
}) => {
	if (!existingMessages?.length) {
		return loadedMessages;
	}

	const loadedMessageIds = new Set(loadedMessages.map((message) => message.id));
	const existingById = new Map(
		existingMessages.map((message) => [message.id, message]),
	);

	return [
		...loadedMessages.map((loadedMessage) => {
			const existingMessage = existingById.get(loadedMessage.id);

			if (!existingMessage) {
				return loadedMessage;
			}

			return {
				...loadedMessage,
				content:
					existingMessage.status === "streaming"
						? existingMessage.content
						: loadedMessage.content,
				reasoning:
					existingMessage.status === "streaming"
						? (existingMessage.reasoning ?? loadedMessage.reasoning)
						: loadedMessage.reasoning,
				timelineParts: mergeTimelinePartsById(
					loadedMessage.timelineParts,
					existingMessage.timelineParts,
				),
			};
		}),
		...existingMessages.filter((message) => !loadedMessageIds.has(message.id)),
	];
};

const shouldResumeActiveRun = (activeRun: ActiveRunSummary) =>
	!(
		activeRun.status === "awaiting_approval" ||
		activeRun.status === "completed" ||
		activeRun.status === "failed"
	);

const resolveResumeCursor = (
	activeRun: ActiveRunSummary,
	existingRun: ConversationRunState | undefined,
) => {
	if (existingRun?.runId !== activeRun.runId) {
		return 0;
	}

	return existingRun.lastEventId ?? 0;
};

const toConversationRunState = (
	activeRun: ActiveRunSummary,
	options?: { lastEventId?: number },
): ConversationRunState => ({
	runId: activeRun.runId,
	assistantMessageId: activeRun.assistantMessageId,
	status:
		activeRun.status === "awaiting_approval"
			? "awaiting_approval"
			: activeRun.status === "resuming" || activeRun.status === "resume_queued"
				? "resuming"
				: "streaming",
	lastEventId: options?.lastEventId ?? activeRun.lastEventId ?? undefined,
	approvalBatch: activeRun.approvalBatch ?? undefined,
});

const reduceStreamUiSideEffects = (
	state: ChatState,
	event: ChatStreamEvent,
): Partial<ChatState> => {
	if (event.type === "title") {
		return {
			conversations: updateConversationTitle(
				state.conversations,
				event.conversationId,
				event.title,
			),
		};
	}

	if (event.type === "error") {
		return {
			error: { message: event.message, scope: "stream" },
		};
	}

	return {};
};

const withoutRecordKey = <T>(
	record: Record<string, T | undefined>,
	key: string,
): Record<string, T | undefined> => {
	const { [key]: _removed, ...rest } = record;
	return rest;
};

const findApprovalBatchInMessages = (
	messages: ChatMessage[],
	batchId: string,
): ApprovalBatch | undefined => {
	for (const message of messages) {
		const batch = message.timelineParts?.find(
			(part) => part.type === "approval" && part.batch.id === batchId,
		);

		if (batch?.type === "approval") {
			return batch.batch;
		}
	}

	return undefined;
};

const findConversationForApprovalBatch = (
	state: ChatState,
	batchId: string,
) => {
	for (const [conversationId, run] of Object.entries(
		state.runsByConversationId,
	)) {
		if (run?.approvalBatch?.id === batchId) {
			return { conversationId, batch: run.approvalBatch, run };
		}
	}

	for (const [conversationId, messages] of Object.entries(
		state.messagesByConversationId,
	)) {
		const batch = findApprovalBatchInMessages(messages, batchId);
		if (batch) {
			return {
				conversationId,
				batch,
				run: state.runsByConversationId[conversationId],
			};
		}
	}

	return undefined;
};

type StartStreamInput = {
	conversationId: string;
	initialMessageId?: string;
	connect: (
		signal: AbortSignal,
		onEvent: (event: ReceivedChatStreamEvent) => void,
	) => Promise<void>;
};

const startStream = async (
	input: StartStreamInput,
	set: (
		partial: Partial<ChatState> | ((state: ChatState) => Partial<ChatState>),
	) => void,
	get: () => ChatState,
) => {
	const currentState = get();
	const currentController =
		currentState.controllersByConversationId[input.conversationId];
	const currentRun = currentState.runsByConversationId[input.conversationId];
	if (
		input.initialMessageId &&
		currentController &&
		!currentController.signal.aborted &&
		currentRun?.assistantMessageId === input.initialMessageId
	) {
		return;
	}

	currentController?.abort();

	const abortController = new AbortController();

	set((state) => ({
		controllersByConversationId: {
			...state.controllersByConversationId,
			[input.conversationId]: abortController,
		},
		error: undefined,
	}));

	try {
		await input.connect(abortController.signal, (received) => {
			set((state) => {
				const eventConversationId =
					received.event.type === "message_created"
						? received.event.message.conversationId
						: input.conversationId;
				const activeRun = state.runsByConversationId[eventConversationId];

				const projected = reduceChatStreamEvent(
					{
						messages: state.messagesByConversationId[eventConversationId] ?? [],
						activeRun,
					},
					received,
				);

				return {
					...reduceStreamUiSideEffects(state, received.event),
					messagesByConversationId: {
						...state.messagesByConversationId,
						[eventConversationId]: projected.messages,
					},
					runsByConversationId: {
						...state.runsByConversationId,
						[eventConversationId]: projected.activeRun,
					},
				};
			});
		});
		await get().loadConversations({ force: true });
	} catch (error) {
		if (!abortController.signal.aborted) {
			if (error instanceof ChatApiError && error.status === 409) {
				await get().selectConversation(input.conversationId, { force: true });
				return;
			}

			const failedMessageId =
				get().runsByConversationId[input.conversationId]?.assistantMessageId ??
				input.initialMessageId;
			set((state) => ({
				controllersByConversationId: withoutRecordKey(
					state.controllersByConversationId,
					input.conversationId,
				),
				error: toChatError(error, "stream"),
				messagesByConversationId: failedMessageId
					? {
							...state.messagesByConversationId,
							[input.conversationId]: updateMessage(
								state.messagesByConversationId[input.conversationId] ?? [],
								failedMessageId,
								(message) => ({ ...message, status: "error" }),
							),
						}
					: state.messagesByConversationId,
			}));
		}
	} finally {
		if (
			get().controllersByConversationId[input.conversationId] ===
			abortController
		) {
			set((state) => ({
				controllersByConversationId: withoutRecordKey(
					state.controllersByConversationId,
					input.conversationId,
				),
			}));
		}
	}
};

const resumeActiveRun = (
	conversationId: string,
	activeRun: ActiveRunSummary | null | undefined,
	afterEventId: number,
	set: (
		partial: Partial<ChatState> | ((state: ChatState) => Partial<ChatState>),
	) => void,
	get: () => ChatState,
) => {
	if (!activeRun) {
		return false;
	}

	if (!shouldResumeActiveRun(activeRun)) {
		return false;
	}

	void startStream(
		{
			conversationId,
			initialMessageId: activeRun.assistantMessageId,
			connect: (signal, onEvent) =>
				resumeChatStream(
					{
						runId: activeRun.runId,
						afterEventId,
					},
					{ signal, onEvent },
				),
		},
		set,
		get,
	);

	return true;
};

export const useChatStore = create<ChatState>((set, get) => ({
	conversations: [],
	messagesByConversationId: {},
	runsByConversationId: {},
	controllersByConversationId: {},
	isLoadingConversations: false,
	isLoadingMessages: false,

	loadConversations: async (options) => {
		if (!options?.force && get().conversations.length > 0) {
			return;
		}

		set({ isLoadingConversations: true, error: undefined });

		try {
			const conversations = await listConversations();
			const activeConversationId =
				get().activeConversationId &&
				conversations.some(
					(conversation) => conversation.id === get().activeConversationId,
				)
					? get().activeConversationId
					: undefined;

			set({
				conversations,
				activeConversationId,
				isLoadingConversations: false,
			});
		} catch (error) {
			set({
				isLoadingConversations: false,
				error: toChatError(error, "conversation"),
			});
		}
	},

	createNewConversation: async () => {
		set({ error: undefined });

		try {
			const conversation = await createConversation();

			set((state) => ({
				conversations: [conversation, ...state.conversations],
				activeConversationId: conversation.id,
				messagesByConversationId: {
					...state.messagesByConversationId,
					[conversation.id]: [],
				},
			}));
		} catch (error) {
			set({ error: toChatError(error, "conversation") });
		}
	},

	clearActiveConversation: () => {
		set({
			activeConversationId: undefined,
			error: undefined,
			isLoadingMessages: false,
		});
	},

	selectConversation: async (conversationId, options) => {
		if (!options?.force && get().activeConversationId === conversationId) {
			return;
		}

		set({ activeConversationId: conversationId, error: undefined });

		set({ isLoadingMessages: true });

		try {
			const { activeRun, messages } = await listMessages(conversationId);
			const existingRun = get().runsByConversationId[conversationId];
			const resumeCursor =
				activeRun && shouldResumeActiveRun(activeRun)
					? resolveResumeCursor(activeRun, existingRun)
					: undefined;

			set((state) => ({
				messagesByConversationId: {
					...state.messagesByConversationId,
					[conversationId]: activeRun
						? mergeLoadedConversationMessagesById({
								existingMessages:
									state.messagesByConversationId[conversationId],
								loadedMessages: messages,
							})
						: messages,
				},
				runsByConversationId: {
					...state.runsByConversationId,
					[conversationId]: activeRun
						? toConversationRunState(activeRun, {
								lastEventId: resumeCursor,
							})
						: undefined,
				},
				isLoadingMessages: false,
			}));
			resumeActiveRun(conversationId, activeRun, resumeCursor ?? 0, set, get);
		} catch (error) {
			set({
				isLoadingMessages: false,
				error: toChatError(error, "message"),
			});
		}
	},

	renameActiveConversation: async (title) => {
		const conversationId = get().activeConversationId;

		if (!conversationId) {
			return;
		}

		set({ error: undefined });

		try {
			const conversation = await renameConversation(conversationId, title);

			set((state) => ({
				conversations: state.conversations.map((item) =>
					item.id === conversation.id ? conversation : item,
				),
			}));
		} catch (error) {
			set({ error: toChatError(error, "conversation") });
		}
	},

	deleteActiveConversation: async () => {
		const conversationId = get().activeConversationId;

		if (!conversationId) {
			return { deleted: false };
		}

		set({ error: undefined });

		try {
			const run = get().runsByConversationId[conversationId];
			if (run) {
				void cancelChatStream(run.assistantMessageId);
				get().controllersByConversationId[conversationId]?.abort();
			}

			await deleteConversation(conversationId);

			set((state) => {
				const conversations = state.conversations.filter(
					(conversation) => conversation.id !== conversationId,
				);
				const {
					[conversationId]: _removedMessages,
					...messagesByConversationId
				} = state.messagesByConversationId;
				const runsByConversationId = withoutRecordKey(
					state.runsByConversationId,
					conversationId,
				);
				const controllersByConversationId = withoutRecordKey(
					state.controllersByConversationId,
					conversationId,
				);

				return {
					conversations,
					activeConversationId: conversations[0]?.id,
					messagesByConversationId,
					runsByConversationId,
					controllersByConversationId,
				};
			});

			const nextConversationId = get().activeConversationId;

			if (nextConversationId) {
				await get().selectConversation(nextConversationId, { force: true });
			}

			return { deleted: true, nextConversationId };
		} catch (error) {
			set({ error: toChatError(error, "conversation") });
			return { deleted: false };
		}
	},

	sendMessage: async (content) => {
		const message = content.trim();

		if (!message) {
			return undefined;
		}

		let conversationId = get().activeConversationId;

		if (!conversationId) {
			try {
				const conversation = await createConversation();
				conversationId = conversation.id;

				set((state) => ({
					conversations: [conversation, ...state.conversations],
					activeConversationId: conversation.id,
					messagesByConversationId: {
						...state.messagesByConversationId,
						[conversation.id]: [],
					},
				}));
			} catch (error) {
				set({ error: toChatError(error, "conversation") });
				return undefined;
			}
		}

		set((state) => ({
			messagesByConversationId: {
				...state.messagesByConversationId,
				[conversationId]: appendOptimisticUserMessage(
					state.messagesByConversationId[conversationId] ?? [],
					conversationId,
					message,
				),
			},
		}));

		const generateTitle =
			get().conversations.find(
				(conversation) => conversation.id === conversationId,
			)?.title === "New chat";

		void startStream(
			{
				conversationId,
				connect: (signal, onEvent) =>
					streamChat(
						{ conversationId, message, generateTitle },
						{ signal, onEvent },
					),
			},
			set,
			get,
		);
		return conversationId;
	},

	submitApproval: async (batchId, selections) => {
		const approval = findConversationForApprovalBatch(get(), batchId);

		if (!approval) {
			set({
				error: {
					message: "Approval request is no longer available",
					scope: "stream",
				},
			});
			return;
		}

		const { batch, conversationId, run } = approval;
		const decisions = batch.requests.map((request) => ({
			approvalRequestId: request.id,
			decision: selections[request.id],
		}));

		if (
			decisions.some(
				(decision) =>
					decision.decision !== "approve" && decision.decision !== "reject",
			)
		) {
			set({
				error: {
					message: "Please approve or reject every tool request",
					scope: "stream",
				},
			});
			return;
		}

		await startStream(
			{
				conversationId,
				initialMessageId: run?.assistantMessageId,
				connect: (signal, onEvent) =>
					submitApprovalDecisions(
						batchId,
						{
							decisions: decisions as Array<{
								approvalRequestId: string;
								decision: "approve" | "reject";
							}>,
							afterEventId: run?.lastEventId ?? 0,
						},
						{ signal, onEvent },
					),
			},
			set,
			get,
		);
	},

	stopStreaming: () => {
		const conversationId = get().activeConversationId;
		if (!conversationId) {
			return;
		}
		const run = get().runsByConversationId[conversationId];
		if (run) {
			void cancelChatStream(run.assistantMessageId);
		}
		get().controllersByConversationId[conversationId]?.abort();

		set((state) => ({
			runsByConversationId: withoutRecordKey(
				state.runsByConversationId,
				conversationId,
			),
			controllersByConversationId: withoutRecordKey(
				state.controllersByConversationId,
				conversationId,
			),
			messagesByConversationId: conversationId
				? {
						...state.messagesByConversationId,
						[conversationId]: (
							state.messagesByConversationId[conversationId] ?? []
						).map((message) =>
							message.status === "streaming"
								? { ...message, status: "done" }
								: message,
						),
					}
				: state.messagesByConversationId,
		}));
	},

	regenerateLastAssistantMessage: async () => {
		const conversationId = get().activeConversationId;

		if (!conversationId) {
			return;
		}

		const lastAssistantMessage = [
			...(get().messagesByConversationId[conversationId] ?? []),
		]
			.reverse()
			.find((message) => message.role === "assistant");

		if (!lastAssistantMessage) {
			return;
		}

		set((state) => ({
			messagesByConversationId: {
				...state.messagesByConversationId,
				[conversationId]: (
					state.messagesByConversationId[conversationId] ?? []
				).map((message) =>
					message.id === lastAssistantMessage.id
						? resetAssistantMessageForRegeneration(message)
						: message,
				),
			},
		}));

		await startStream(
			{
				conversationId,
				initialMessageId: lastAssistantMessage.id,
				connect: (signal, onEvent) =>
					streamChat(
						{
							conversationId,
							message: "",
							regenerateFromMessageId: lastAssistantMessage.id,
						},
						{ signal, onEvent },
					),
			},
			set,
			get,
		);
	},

	editUserMessageAndRegenerate: async (
		messageId,
		previousContent,
		nextContent,
	) => {
		const conversationId = get().activeConversationId;
		const normalizedNextContent = nextContent.trim();

		if (!conversationId || !normalizedNextContent) {
			return;
		}

		set({ error: undefined });

		const messages = get().messagesByConversationId[conversationId] ?? [];
		const messageIndex = messages.findIndex(
			(message) => message.id === messageId,
		);

		if (messageIndex === -1) {
			return;
		}

		set((state) => ({
			messagesByConversationId: {
				...state.messagesByConversationId,
				[conversationId]: (
					state.messagesByConversationId[conversationId] ?? messages
				).map((message) =>
					message.id === messageId
						? { ...message, content: normalizedNextContent }
						: message,
				),
			},
		}));

		try {
			const message = await editMessage(messageId, normalizedNextContent);

			set((state) => ({
				messagesByConversationId: {
					...state.messagesByConversationId,
					[conversationId]: (
						state.messagesByConversationId[conversationId] ?? []
					)
						.slice(0, messageIndex + 1)
						.map((currentMessage) =>
							currentMessage.id === messageId ? message : currentMessage,
						),
				},
			}));

			await startStream(
				{
					conversationId,
					connect: (signal, onEvent) =>
						streamChat(
							{
								conversationId,
								message: normalizedNextContent,
								parentMessageId: messageId,
							},
							{ signal, onEvent },
						),
				},
				set,
				get,
			);
		} catch (error) {
			set((state) => ({
				error: toChatError(error, "message"),
				messagesByConversationId: {
					...state.messagesByConversationId,
					[conversationId]: (
						state.messagesByConversationId[conversationId] ?? messages
					).map((message) =>
						message.id === messageId
							? { ...message, content: previousContent }
							: message,
					),
				},
			}));
		}
	},

	clearError: () => {
		set({ error: undefined });
	},
}));
