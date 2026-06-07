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
} from "./api";
import { reduceChatStreamEvent } from "./chat-event-reducer";
import type {
	ActiveRunSummary,
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

type ChatState = {
	conversations: Conversation[];
	activeConversationId?: string;
	messagesByConversationId: Record<string, ChatMessage[]>;
	activeRunsByConversationId: Record<string, ConversationRunState | undefined>;
	isLoadingConversations: boolean;
	isLoadingMessages: boolean;
	isStreaming: boolean;
	streamingConversationId?: string;
	streamingMessageId?: string;
	error?: ChatError;
	abortController?: AbortController;
	loadConversations: (options?: LoadConversationsOptions) => Promise<void>;
	createNewConversation: () => Promise<void>;
	clearActiveConversation: () => void;
	selectConversation: (conversationId: string) => Promise<void>;
	renameActiveConversation: (title: string) => Promise<void>;
	deleteActiveConversation: () => Promise<{
		deleted: boolean;
		nextConversationId?: string;
	}>;
	sendMessage: (content: string) => Promise<string | undefined>;
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

const toConversationRunState = (
	activeRun: ActiveRunSummary,
): ConversationRunState => ({
	runId: activeRun.runId,
	assistantMessageId: activeRun.assistantMessageId,
	status:
		activeRun.status === "awaiting_approval"
			? "awaiting_approval"
			: activeRun.status === "resuming" || activeRun.status === "resume_queued"
				? "resuming"
				: "streaming",
	lastEventId: activeRun.lastEventId ?? undefined,
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

	if (event.type === "run_created") {
		return {
			streamingMessageId: event.assistantMessageId,
		};
	}

	if (event.type === "error") {
		return {
			isStreaming: false,
			streamingConversationId: undefined,
			streamingMessageId: undefined,
			abortController: undefined,
			error: { message: event.message, scope: "stream" },
		};
	}

	if (event.type === "message_created") {
		return {
			streamingMessageId: event.message.id,
		};
	}

	if (event.type === "done") {
		return {
			isStreaming: false,
			streamingConversationId: undefined,
			streamingMessageId: undefined,
			abortController: undefined,
		};
	}

	return {};
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
	if (
		input.initialMessageId &&
		currentState.isStreaming &&
		currentState.streamingMessageId === input.initialMessageId
	) {
		return;
	}

	currentState.abortController?.abort();

	const abortController = new AbortController();

	set({
		isStreaming: true,
		streamingConversationId: input.conversationId,
		streamingMessageId: input.initialMessageId,
		abortController,
		error: undefined,
	});

	try {
		await input.connect(abortController.signal, (received) => {
			set((state) => {
				const eventConversationId =
					received.event.type === "message_created"
						? received.event.message.conversationId
						: input.conversationId;
				const activeRun = state.activeRunsByConversationId[eventConversationId];

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
					activeRunsByConversationId: {
						...state.activeRunsByConversationId,
						[eventConversationId]: projected.activeRun,
					},
				};
			});
		});
		await get().loadConversations({ force: true });
	} catch (error) {
		if (!abortController.signal.aborted) {
			if (error instanceof ChatApiError && error.status === 409) {
				await get().selectConversation(input.conversationId);
				return;
			}

			const failedMessageId =
				get().streamingMessageId ?? input.initialMessageId;
			set((state) => ({
				isStreaming: false,
				streamingConversationId: undefined,
				streamingMessageId: undefined,
				abortController: undefined,
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
		if (get().abortController === abortController) {
			set({
				isStreaming: false,
				streamingConversationId: undefined,
				streamingMessageId: undefined,
				abortController: undefined,
			});
		}
	}
};

const resumeActiveRun = (
	conversationId: string,
	activeRun: ActiveRunSummary | null | undefined,
	set: (
		partial: Partial<ChatState> | ((state: ChatState) => Partial<ChatState>),
	) => void,
	get: () => ChatState,
) => {
	if (!activeRun) {
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
						afterEventId: activeRun.lastEventId ?? 0,
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
	activeRunsByConversationId: {},
	isLoadingConversations: false,
	isLoadingMessages: false,
	isStreaming: false,

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

	selectConversation: async (conversationId) => {
		set({ activeConversationId: conversationId, error: undefined });

		set({ isLoadingMessages: true });

		try {
			const { activeRun, messages } = await listMessages(conversationId);

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
				activeRunsByConversationId: {
					...state.activeRunsByConversationId,
					[conversationId]: activeRun
						? toConversationRunState(activeRun)
						: undefined,
				},
				isLoadingMessages: false,
			}));
			resumeActiveRun(conversationId, activeRun, set, get);
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
			if (get().streamingConversationId === conversationId) {
				const { streamingMessageId } = get();
				if (streamingMessageId) {
					void cancelChatStream(streamingMessageId);
				}
				get().abortController?.abort();
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

				return {
					conversations,
					activeConversationId: conversations[0]?.id,
					messagesByConversationId,
					isStreaming:
						state.streamingConversationId === conversationId
							? false
							: state.isStreaming,
					streamingConversationId:
						state.streamingConversationId === conversationId
							? undefined
							: state.streamingConversationId,
					streamingMessageId:
						state.streamingConversationId === conversationId
							? undefined
							: state.streamingMessageId,
					abortController:
						state.streamingConversationId === conversationId
							? undefined
							: state.abortController,
				};
			});

			const nextConversationId = get().activeConversationId;

			if (nextConversationId) {
				await get().selectConversation(nextConversationId);
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

	stopStreaming: () => {
		const { abortController, streamingConversationId, streamingMessageId } =
			get();
		if (streamingMessageId) {
			void cancelChatStream(streamingMessageId);
		}
		abortController?.abort();

		set((state) => ({
			isStreaming: false,
			streamingConversationId: undefined,
			streamingMessageId: undefined,
			abortController: undefined,
			messagesByConversationId: streamingConversationId
				? {
						...state.messagesByConversationId,
						[streamingConversationId]: (
							state.messagesByConversationId[streamingConversationId] ?? []
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

		await startStream(
			{
				conversationId,
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
