import { create } from "zustand";
import {
	createConversation,
	deleteConversation,
	editMessage,
	listConversations,
	listMessages,
	renameConversation,
	streamChat,
} from "./api";
import type {
	ChatError,
	ChatMessage,
	ChatStreamEvent,
	Conversation,
	StreamChatRequest,
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
	error?: ChatError;
	abortController?: AbortController;
	loadConversations: () => Promise<void>;
	createNewConversation: () => Promise<void>;
	selectConversation: (conversationId: string) => Promise<void>;
	renameActiveConversation: (title: string) => Promise<void>;
	deleteActiveConversation: () => Promise<void>;
	sendMessage: (content: string) => Promise<void>;
	stopStreaming: () => void;
	regenerateLastAssistantMessage: () => Promise<void>;
	editUserMessageAndRegenerate: (
		messageId: string,
		content: string,
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
		index === messageIndex ? { ...message, ...nextMessage } : message,
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

const startStream = async (
	request: StreamChatRequest,
	set: (
		partial: Partial<ChatState> | ((state: ChatState) => Partial<ChatState>),
	) => void,
	get: () => ChatState,
) => {
	get().abortController?.abort();

	const abortController = new AbortController();

	set({
		isStreaming: true,
		streamingConversationId: request.conversationId,
		abortController,
		error: undefined,
	});

	try {
		await streamChat(request, {
			signal: abortController.signal,
			onEvent: (event) => {
				set((state) => reduceStreamEvent(state, event, request.conversationId));
			},
		});
	} catch (error) {
		if (!abortController.signal.aborted) {
			set({
				isStreaming: false,
				streamingConversationId: undefined,
				abortController: undefined,
				error: toChatError(error, "stream"),
			});
		}
	} finally {
		if (get().abortController === abortController) {
			set({
				isStreaming: false,
				streamingConversationId: undefined,
				abortController: undefined,
			});
		}
	}
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
					: conversations[0]?.id;

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

	selectConversation: async (conversationId) => {
		set({ activeConversationId: conversationId, error: undefined });

		if (get().messagesByConversationId[conversationId]) {
			return;
		}

		set({ isLoadingMessages: true });

		try {
			const messages = await listMessages(conversationId);

			set((state) => ({
				messagesByConversationId: {
					...state.messagesByConversationId,
					[conversationId]: messages,
				},
				isLoadingMessages: false,
			}));
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
			return;
		}

		set({ error: undefined });

		try {
			if (get().streamingConversationId === conversationId) {
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
					abortController:
						state.streamingConversationId === conversationId
							? undefined
							: state.abortController,
				};
			});
		} catch (error) {
			set({ error: toChatError(error, "conversation") });
		}
	},

	sendMessage: async (content) => {
		const message = content.trim();

		if (!message) {
			return;
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
				return;
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

		await startStream({ conversationId, message }, set, get);
	},

	stopStreaming: () => {
		const { abortController, streamingConversationId } = get();
		abortController?.abort();

		set((state) => ({
			isStreaming: false,
			streamingConversationId: undefined,
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
				message: "",
				regenerateFromMessageId: lastAssistantMessage.id,
			},
			set,
			get,
		);
	},

	editUserMessageAndRegenerate: async (messageId, content) => {
		const conversationId = get().activeConversationId;
		const nextContent = content.trim();

		if (!conversationId || !nextContent) {
			return;
		}

		set({ error: undefined });

		try {
			const message = await editMessage(messageId, nextContent);

			set((state) => ({
				messagesByConversationId: {
					...state.messagesByConversationId,
					[conversationId]: updateMessage(
						state.messagesByConversationId[conversationId] ?? [],
						messageId,
						() => message,
					),
				},
			}));

			await startStream(
				{
					conversationId,
					message: nextContent,
					parentMessageId: messageId,
				},
				set,
				get,
			);
		} catch (error) {
			set({ error: toChatError(error, "message") });
		}
	},

	clearError: () => {
		set({ error: undefined });
	},
}));
