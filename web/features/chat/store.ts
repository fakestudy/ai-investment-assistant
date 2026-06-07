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
	appendReasoningTimelinePart,
	resetStreamCreatedMessage,
	upsertToolTimelinePart,
} from "./chat-ui-state";
import type {
	ActiveRunSummary,
	ApprovalBatch,
	ChatError,
	ChatMessage,
	ChatStreamEvent,
	ChatTimelinePart,
	Conversation,
	ToolInvocation,
} from "./types";

type LoadConversationsOptions = {
	force?: boolean;
};

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

const upsertApprovalTimelinePart = (
	parts: ChatMessage["timelineParts"],
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

const updateApprovalTimelineBatch = (
	parts: ChatMessage["timelineParts"],
	batch: ApprovalBatch,
) =>
	parts?.map((part) =>
		part.type === "approval" && part.batch.id === batch.id
			? { ...part, batch }
			: part,
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

	if (event.type === "run_created") {
		return {
			streamingMessageId: event.assistantMessageId,
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
						timelineParts: appendReasoningTimelinePart(message.timelineParts, {
							id: createLocalId(),
							text: event.text,
						}),
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
						timelineParts: upsertToolTimelinePart(
							message.timelineParts,
							event.invocation,
						),
						status: "streaming",
					}),
				),
			},
		};
	}

	if (event.type === "approval_required") {
		return {
			messagesByConversationId: {
				...state.messagesByConversationId,
				[conversationId]: updateMessage(
					messages,
					event.messageId,
					(message) => ({
						...message,
						timelineParts: upsertApprovalTimelinePart(
							message.timelineParts,
							event.part,
						),
						status: "streaming",
					}),
				),
			},
		};
	}

	if (event.type === "approval_resolved") {
		return {
			messagesByConversationId: {
				...state.messagesByConversationId,
				[conversationId]: messages.map((message) => ({
					...message,
					timelineParts: updateApprovalTimelineBatch(
						message.timelineParts,
						event.batch,
					),
					status:
						message.timelineParts?.some(
							(part) =>
								part.type === "approval" && part.batch.id === event.batch.id,
						) && message.status !== "done"
							? "streaming"
							: message.status,
				})),
			},
		};
	}

	if (event.type === "done") {
		return {
			isStreaming: false,
			streamingConversationId: undefined,
			streamingMessageId: undefined,
			abortController: undefined,
			messagesByConversationId: {
				...state.messagesByConversationId,
				[conversationId]: updateMessage(
					messages,
					event.messageId,
					(message) => ({
						...message,
						status: "done",
					}),
				),
			},
		};
	}

	return {};
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
		await get().loadConversations({ force: true });
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
