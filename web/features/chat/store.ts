import { create } from "zustand";
import {
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
import {
	getLatestStreamingAssistantMessageId,
	getResumableStreamingMessageId,
	resetStreamCreatedMessage,
	resolveLoadedConversationMessages,
} from "./chat-ui-state";
import type {
	ChatError,
	ChatMessage,
	ChatStreamEvent,
	Conversation,
	ToolInvocation,
} from "./types";

type ChatState = {
	conversations: Conversation[];
	activeConversationId?: string;
	messagesByConversationId: Record<string, ChatMessage[]>;
	isLoadingConversations: boolean;
	isLoadingMessages: boolean;
	isStreaming: boolean;
	streamingConversationId?: string;
	streamingMessageId?: string;
	error?: ChatError;
	abortController?: AbortController;
	loadConversations: () => Promise<void>;
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

const reduceStreamEvent = (
	state: ChatState,
	event: ChatStreamEvent,
	streamConversationId: string,
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
		const nextState: Partial<ChatState> = {
			isStreaming: false,
			streamingConversationId: undefined,
			streamingMessageId: undefined,
			abortController: undefined,
			error: { message: event.message, scope: "stream" },
		};

		if (event.messageId) {
			nextState.messagesByConversationId = {
				...state.messagesByConversationId,
				[streamConversationId]: updateMessage(
					state.messagesByConversationId[streamConversationId] ?? [],
					event.messageId,
					(message) => ({ ...message, status: "error" }),
				),
			};
		}

		return nextState;
	}

	const conversationId =
		event.type === "message_created"
			? event.message.conversationId
			: streamConversationId;

	const messages = state.messagesByConversationId[conversationId] ?? [];

	if (
		event.type !== "message_created" &&
		!(conversationId in state.messagesByConversationId)
	) {
		return {};
	}

	if (event.type === "message_created") {
		return {
			streamingMessageId: event.message.id,
			messagesByConversationId: {
				...state.messagesByConversationId,
				[conversationId]: upsertMessage(messages, event.message),
			},
		};
	}

	if (event.type === "delta") {
		return {
			messagesByConversationId: {
				...state.messagesByConversationId,
				[conversationId]: updateMessage(
					messages,
					event.messageId,
					(message) => ({
						...message,
						content: `${message.content}${event.text}`,
						status: "streaming",
					}),
				),
			},
		};
	}

	if (event.type === "reasoning") {
		return {
			messagesByConversationId: {
				...state.messagesByConversationId,
				[conversationId]: updateMessage(
					messages,
					event.messageId,
					(message) => ({
						...message,
						reasoning: `${message.reasoning ?? ""}${event.text}`,
						status: "streaming",
					}),
				),
			},
		};
	}

	if (event.type === "tool_call" || event.type === "tool_result") {
		return {
			messagesByConversationId: {
				...state.messagesByConversationId,
				[conversationId]: updateMessage(
					messages,
					event.messageId,
					(message) => ({
						...message,
						toolInvocations: upsertToolInvocation(
							message.toolInvocations,
							event.invocation,
						),
						status: "streaming",
					}),
				),
			},
		};
	}

	return {
		isStreaming: false,
		streamingConversationId: undefined,
		streamingMessageId: undefined,
		abortController: undefined,
		messagesByConversationId: {
			...state.messagesByConversationId,
			[conversationId]: updateMessage(messages, event.messageId, (message) => ({
				...message,
				status: "done",
			})),
		},
	};
};

type StartStreamInput = {
	conversationId: string;
	initialMessageId?: string;
	connect: (
		signal: AbortSignal,
		onEvent: (event: ChatStreamEvent) => void,
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
		await input.connect(abortController.signal, (event) => {
			set((state) => reduceStreamEvent(state, event, input.conversationId));
		});
	} catch (error) {
		if (!abortController.signal.aborted) {
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

const resumeStreamingMessage = (
	conversationId: string,
	messages: ChatMessage[],
	set: (
		partial: Partial<ChatState> | ((state: ChatState) => Partial<ChatState>),
	) => void,
	get: () => ChatState,
) => {
	const messageId = getLatestStreamingAssistantMessageId(messages);
	if (!messageId) {
		return;
	}

	void startStream(
		{
			conversationId,
			initialMessageId: messageId,
			connect: (signal, onEvent) =>
				resumeChatStream(messageId, { signal, onEvent }),
		},
		set,
		get,
	);
};

export const useChatStore = create<ChatState>((set, get) => ({
	conversations: [],
	messagesByConversationId: {},
	isLoadingConversations: false,
	isLoadingMessages: false,
	isStreaming: false,

	loadConversations: async () => {
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

		const cachedMessages = get().messagesByConversationId[conversationId];
		if (cachedMessages) {
			const resumableMessageId = getResumableStreamingMessageId({
				messages: cachedMessages,
				isStreaming: get().isStreaming,
				streamingMessageId: get().streamingMessageId,
			});
			if (resumableMessageId) {
				resumeStreamingMessage(conversationId, cachedMessages, set, get);
			}
			return;
		}

		set({ isLoadingMessages: true });

		try {
			const messages = await listMessages(conversationId);

			set((state) => ({
				messagesByConversationId: {
					...state.messagesByConversationId,
					[conversationId]: resolveLoadedConversationMessages({
						existingMessages: state.messagesByConversationId[conversationId],
						loadedMessages: messages,
					}),
				},
				isLoadingMessages: false,
			}));
			resumeStreamingMessage(conversationId, messages, set, get);
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

		void startStream(
			{
				conversationId,
				connect: (signal, onEvent) =>
					streamChat({ conversationId, message }, { signal, onEvent }),
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
