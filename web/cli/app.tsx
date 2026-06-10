import { Box, Spacer, Text, useApp, useInput } from "ink";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
	submitApprovalDecisions,
} from "../features/chat/api";
import {
	getNextSlashCommandIndex,
	getSlashCommandSuggestions,
	isExactSlashCommand,
} from "../features/chat/slash-commands";
import type {
	ActiveRunSummary,
	ChatMessage,
	Conversation,
	ConversationRunState,
	ReceivedChatStreamEvent,
} from "../features/chat/types";
import {
	type CliInputAction,
	type CliStreamState,
	createFreshCliBootState,
	findPendingApprovalBatch,
	getCliStatus,
	parseCliInput,
	projectCliStreamEvent,
} from "./chat-cli-state";

type ChatCliClient = {
	listConversations: typeof listConversations;
	createConversation: typeof createConversation;
	renameConversation: typeof renameConversation;
	deleteConversation: typeof deleteConversation;
	listMessages: typeof listMessages;
	editMessage: typeof editMessage;
	streamChat: typeof streamChat;
	resumeChatStream: typeof resumeChatStream;
	submitApprovalDecisions: typeof submitApprovalDecisions;
	cancelChatStream: typeof cancelChatStream;
};

type RuntimePhase = "booting" | "ready" | "loading" | "streaming" | "error";

const defaultClient: ChatCliClient = {
	listConversations,
	createConversation,
	renameConversation,
	deleteConversation,
	listMessages,
	editMessage,
	streamChat,
	resumeChatStream,
	submitApprovalDecisions,
	cancelChatStream,
};

const helpLines = [
	"/new              start a new conversation",
	"/sessions         list recent conversations",
	"/switch <id|#>    switch by id prefix or list number",
	"/rename <title>   rename the current conversation",
	"/delete           delete the current conversation",
	"/stop             stop the current stream",
	"/approve          approve all pending tool requests",
	"/reject           reject all pending tool requests",
	"/regenerate       regenerate the last assistant response",
	"/edit <id|#> ...  edit a user message and regenerate",
	"/get-balance      query DeepSeek account balance",
	"/help             show commands",
	"/quit             exit",
];

function createLocalId() {
	return `cli-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function isResumableRun(
	activeRun: ActiveRunSummary | null | undefined,
): activeRun is ActiveRunSummary {
	return (
		!!activeRun &&
		activeRun.status !== "awaiting_approval" &&
		activeRun.status !== "completed" &&
		activeRun.status !== "failed"
	);
}

function toConversationRunState(
	activeRun: ActiveRunSummary,
): ConversationRunState {
	return {
		runId: activeRun.runId,
		assistantMessageId: activeRun.assistantMessageId,
		status:
			activeRun.status === "awaiting_approval"
				? "awaiting_approval"
				: activeRun.status === "resuming" ||
						activeRun.status === "resume_queued"
					? "resuming"
					: "streaming",
		lastEventId: activeRun.lastEventId ?? undefined,
		approvalBatch: activeRun.approvalBatch ?? undefined,
	};
}

function formatConversationLabel(conversation: Conversation, index: number) {
	const title = conversation.title || "Untitled chat";
	return `#${index + 1} ${title}  ${conversation.id.slice(0, 8)}`;
}

function resolveConversationTarget(
	conversations: Conversation[],
	target: string,
) {
	const index = target.startsWith("#")
		? Number.parseInt(target.slice(1), 10) - 1
		: Number.NaN;
	if (Number.isInteger(index) && conversations[index]) {
		return conversations[index];
	}

	return conversations.find((conversation) =>
		conversation.id.startsWith(target),
	);
}

function trimText(text: string, maxLength: number) {
	if (text.length <= maxLength) {
		return text;
	}

	return `${text.slice(0, maxLength - 1)}…`;
}

function resolveMessageTarget(messages: ChatMessage[], target: string) {
	const index = target.startsWith("#")
		? Number.parseInt(target.slice(1), 10) - 1
		: Number.NaN;
	if (Number.isInteger(index) && messages[index]) {
		return messages[index];
	}

	return messages.find((message) => message.id.startsWith(target));
}

function findLastAssistantMessage(messages: ChatMessage[]) {
	return [...messages]
		.reverse()
		.find((message) => message.role === "assistant");
}

function getMessageLabel(message: ChatMessage) {
	if (message.role === "user") {
		return { text: "you", color: "cyan" as const, marker: "›" };
	}

	if (message.role === "tool") {
		return { text: "tool", color: "yellow" as const, marker: "◆" };
	}

	return { text: "assistant", color: "green" as const, marker: "●" };
}

function getMessageBody(message: ChatMessage) {
	if (message.content) {
		return message.content;
	}

	const approval = message.timelineParts?.find(
		(part) => part.type === "approval",
	);
	if (approval?.type === "approval") {
		return `approval required: ${approval.batch.requests.length} request(s)`;
	}

	const tool = message.timelineParts?.findLast?.(
		(part) => part.type === "tool",
	);
	if (tool?.type === "tool") {
		return `${tool.invocation.toolName} ${tool.invocation.status}`;
	}

	if (message.reasoning) {
		return `thinking: ${message.reasoning}`;
	}

	return message.status === "streaming" ? "thinking..." : "";
}

function ChatMessageView({
	displayIndex,
	message,
}: {
	displayIndex: number;
	message: ChatMessage;
}) {
	const label = getMessageLabel(message);
	const body = getMessageBody(message);
	const reasoning =
		message.reasoning && message.content
			? trimText(message.reasoning.replace(/\s+/g, " "), 140)
			: undefined;

	return (
		<Box flexDirection="column" marginBottom={1}>
			<Text>
				<Text color="gray">#{displayIndex}</Text>{" "}
				<Text color={label.color}>{label.marker}</Text>{" "}
				<Text color={label.color}>{label.text}</Text>
				{message.status === "streaming" ? (
					<Text color="gray"> streaming</Text>
				) : null}
			</Text>
			{reasoning ? <Text color="gray"> reasoning: {reasoning}</Text> : null}
			<Text wrap="wrap"> {body || " "}</Text>
		</Box>
	);
}

function ApprovalPanel({ state }: { state: CliStreamState }) {
	const batch = findPendingApprovalBatch(state);
	if (!batch) {
		return null;
	}

	return (
		<Box
			flexDirection="column"
			borderStyle="round"
			borderColor="yellow"
			paddingX={1}
		>
			<Text color="yellow">approval required</Text>
			{batch.requests.map((request) => (
				<Text key={request.id}>
					{request.toolName} {JSON.stringify(request.args)}
				</Text>
			))}
			<Text color="gray">/approve to continue, /reject to deny</Text>
		</Box>
	);
}

function NoticePanel({ lines }: { lines: string[] }) {
	if (lines.length === 0) {
		return null;
	}

	return (
		<Box
			flexDirection="column"
			borderStyle="single"
			borderColor="gray"
			paddingX={1}
		>
			{lines.map((line) => (
				<Text color="gray" key={line}>
					{line}
				</Text>
			))}
		</Box>
	);
}

export function ChatCliApp({
	client = defaultClient,
	apiBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:3000",
}: {
	client?: ChatCliClient;
	apiBase?: string;
}) {
	const { exit } = useApp();
	const abortRef = useRef<AbortController | undefined>(undefined);
	const [phase, setPhase] = useState<RuntimePhase>("booting");
	const [conversations, setConversations] = useState<Conversation[]>([]);
	const [activeConversationId, setActiveConversationId] = useState<string>();
	const [input, setInput] = useState("");
	const [selectedCommandIndex, setSelectedCommandIndex] = useState(0);
	const [noticeLines, setNoticeLines] = useState<string[]>(helpLines);
	const [error, setError] = useState<string>();
	const [streamState, setStreamState] = useState<CliStreamState>({
		messages: [],
	});

	const activeConversation = useMemo(
		() =>
			conversations.find(
				(conversation) => conversation.id === activeConversationId,
			),
		[activeConversationId, conversations],
	);

	const activeTitle =
		streamState.title ?? activeConversation?.title ?? "New chat";
	const commandSuggestions = getSlashCommandSuggestions(input);
	const selectedCommandOptionIndex = commandSuggestions[selectedCommandIndex]
		? selectedCommandIndex
		: 0;
	const selectedCommand =
		commandSuggestions[selectedCommandOptionIndex] ?? commandSuggestions[0];

	const refreshConversations = useCallback(async () => {
		const nextConversations = await client.listConversations();
		setConversations(nextConversations);
		return nextConversations;
	}, [client]);

	const applyStreamEvent = useCallback((received: ReceivedChatStreamEvent) => {
		setStreamState((state) => projectCliStreamEvent(state, received));
	}, []);

	const startStream = useCallback(
		async (
			connect: (
				signal: AbortSignal,
				onEvent: (event: ReceivedChatStreamEvent) => void,
			) => Promise<void>,
		) => {
			abortRef.current?.abort();
			const controller = new AbortController();
			abortRef.current = controller;
			setPhase("streaming");
			setError(undefined);

			try {
				await connect(controller.signal, applyStreamEvent);
				await refreshConversations();
				setPhase("ready");
			} catch (streamError) {
				if (controller.signal.aborted) {
					setPhase("ready");
					return;
				}

				setPhase("error");
				setError(
					streamError instanceof Error
						? streamError.message
						: "Unexpected stream error",
				);
			} finally {
				if (abortRef.current === controller) {
					abortRef.current = undefined;
				}
			}
		},
		[applyStreamEvent, refreshConversations],
	);

	const loadConversation = useCallback(
		async (conversation: Conversation) => {
			setPhase("loading");
			setError(undefined);

			try {
				const { activeRun, messages } = await client.listMessages(
					conversation.id,
				);
				setActiveConversationId(conversation.id);
				setStreamState({
					messages,
					activeRun: activeRun ? toConversationRunState(activeRun) : undefined,
					title: conversation.title,
				});
				setNoticeLines([
					`switched to ${conversation.title || conversation.id}`,
				]);
				setPhase("ready");

				if (isResumableRun(activeRun)) {
					void startStream((signal, onEvent) =>
						client.resumeChatStream(
							{
								runId: activeRun.runId,
								afterEventId: activeRun.lastEventId ?? 0,
							},
							{ signal, onEvent },
						),
					);
				}
			} catch (loadError) {
				setPhase("error");
				setError(
					loadError instanceof Error
						? loadError.message
						: "Unexpected conversation load error",
				);
			}
		},
		[client, startStream],
	);

	useEffect(() => {
		let cancelled = false;

		async function boot() {
			try {
				const nextConversations = await client.listConversations();
				if (cancelled) {
					return;
				}

				const bootState = createFreshCliBootState(nextConversations);
				setConversations(bootState.conversations);
				setActiveConversationId(bootState.activeConversationId);
				setStreamState(bootState.streamState);
				setNoticeLines(bootState.noticeLines);
				setPhase("ready");
			} catch (bootError) {
				if (!cancelled) {
					setPhase("error");
					setError(
						bootError instanceof Error
							? bootError.message
							: "Unexpected boot error",
					);
				}
			}
		}

		void boot();
		return () => {
			cancelled = true;
			abortRef.current?.abort();
		};
	}, [client]);

	const stopStreaming = useCallback(() => {
		const activeRun = streamState.activeRun;
		if (activeRun) {
			void client.cancelChatStream(activeRun.assistantMessageId);
		}

		abortRef.current?.abort();
		setStreamState((state) => ({
			...state,
			activeRun: undefined,
			messages: state.messages.map((message) =>
				message.status === "streaming"
					? { ...message, status: "done" }
					: message,
			),
		}));
		setPhase("ready");
		setNoticeLines(["stream stopped"]);
	}, [client, streamState.activeRun]);

	const renameActiveConversation = useCallback(
		async (title: string) => {
			if (!activeConversationId) {
				setNoticeLines(["No active conversation to rename."]);
				return;
			}

			try {
				const conversation = await client.renameConversation(
					activeConversationId,
					title,
				);
				setConversations((items) =>
					items.map((item) =>
						item.id === conversation.id ? conversation : item,
					),
				);
				setStreamState((state) => ({ ...state, title: conversation.title }));
				setNoticeLines([`renamed to ${conversation.title}`]);
				setError(undefined);
			} catch (renameError) {
				setPhase("error");
				setError(
					renameError instanceof Error
						? renameError.message
						: "Unexpected rename error",
				);
			}
		},
		[activeConversationId, client],
	);

	const deleteActiveConversation = useCallback(async () => {
		if (!activeConversationId) {
			setNoticeLines(["No active conversation to delete."]);
			return;
		}

		try {
			if (streamState.activeRun) {
				void client.cancelChatStream(streamState.activeRun.assistantMessageId);
				abortRef.current?.abort();
			}

			await client.deleteConversation(activeConversationId);
			const nextConversations = await refreshConversations();
			const bootState = createFreshCliBootState(nextConversations);
			setActiveConversationId(bootState.activeConversationId);
			setStreamState(bootState.streamState);
			setNoticeLines(["conversation deleted", ...bootState.noticeLines]);
			setPhase("ready");
			setError(undefined);
		} catch (deleteError) {
			setPhase("error");
			setError(
				deleteError instanceof Error
					? deleteError.message
					: "Unexpected delete error",
			);
		}
	}, [
		activeConversationId,
		client,
		refreshConversations,
		streamState.activeRun,
	]);

	const sendMessage = useCallback(
		async (message: string) => {
			if (streamState.activeRun) {
				setNoticeLines([
					"A run is active. Use /stop before sending another message.",
				]);
				return;
			}

			let conversationId = activeConversationId;
			let conversationTitle = activeTitle;

			try {
				if (!conversationId) {
					const conversation = await client.createConversation();
					conversationId = conversation.id;
					conversationTitle = conversation.title;
					setActiveConversationId(conversation.id);
					setConversations((items) => [conversation, ...items]);
				}

				const targetConversationId = conversationId;
				const userMessage: ChatMessage = {
					id: createLocalId(),
					conversationId: targetConversationId,
					role: "user",
					content: message,
					status: "done",
					createdAt: new Date().toISOString(),
				};

				setStreamState((state) => ({
					...state,
					title: conversationTitle,
					messages: [...state.messages, userMessage],
				}));
				setNoticeLines([]);

				const generateTitle =
					!conversationTitle || conversationTitle === "New chat";
				await startStream((signal, onEvent) =>
					client.streamChat(
						{ conversationId: targetConversationId, message, generateTitle },
						{ signal, onEvent },
					),
				);
			} catch (sendError) {
				setPhase("error");
				setError(
					sendError instanceof Error
						? sendError.message
						: "Unexpected send error",
				);
			}
		},
		[
			activeConversationId,
			activeTitle,
			client,
			startStream,
			streamState.activeRun,
		],
	);

	const submitApproval = useCallback(
		async (decision: "approve" | "reject") => {
			const batch = findPendingApprovalBatch(streamState);
			if (!batch) {
				setNoticeLines(["No pending approval request."]);
				return;
			}

			await startStream((signal, onEvent) =>
				client.submitApprovalDecisions(
					batch.id,
					{
						afterEventId: streamState.activeRun?.lastEventId ?? 0,
						decisions: batch.requests.map((request) => ({
							approvalRequestId: request.id,
							decision,
						})),
					},
					{ signal, onEvent },
				),
			);
		},
		[client, startStream, streamState],
	);

	const regenerateLastAssistantMessage = useCallback(async () => {
		if (streamState.activeRun) {
			setNoticeLines([
				"A run is active. Use /stop before regenerating the response.",
			]);
			return;
		}

		if (!activeConversationId) {
			setNoticeLines(["No active conversation to regenerate."]);
			return;
		}

		const assistantMessage = findLastAssistantMessage(streamState.messages);
		if (!assistantMessage) {
			setNoticeLines(["No assistant message to regenerate."]);
			return;
		}

		setStreamState((state) => ({
			...state,
			messages: state.messages.map((message) =>
				message.id === assistantMessage.id
					? {
							...message,
							content: "",
							reasoning: undefined,
							toolInvocations: undefined,
							timelineParts: undefined,
							status: "streaming",
						}
					: message,
			),
		}));
		setNoticeLines([]);

		await startStream((signal, onEvent) =>
			client.streamChat(
				{
					conversationId: activeConversationId,
					message: "",
					regenerateFromMessageId: assistantMessage.id,
				},
				{ signal, onEvent },
			),
		);
	}, [
		activeConversationId,
		client,
		startStream,
		streamState.activeRun,
		streamState.messages,
	]);

	const editUserMessageAndRegenerate = useCallback(
		async (target: string, message: string) => {
			if (streamState.activeRun) {
				setNoticeLines([
					"A run is active. Use /stop before editing a message.",
				]);
				return;
			}

			if (!activeConversationId) {
				setNoticeLines(["No active conversation to edit."]);
				return;
			}

			const targetMessage = resolveMessageTarget(streamState.messages, target);
			if (!targetMessage) {
				setNoticeLines([`No message matches ${target}.`]);
				return;
			}

			if (targetMessage.role !== "user") {
				setNoticeLines(["Only user messages can be edited."]);
				return;
			}

			const messageIndex = streamState.messages.findIndex(
				(item) => item.id === targetMessage.id,
			);
			try {
				const editedMessage = await client.editMessage(
					targetMessage.id,
					message,
				);
				setStreamState((state) => ({
					...state,
					messages: state.messages
						.slice(0, messageIndex + 1)
						.map((item) =>
							item.id === editedMessage.id ? editedMessage : item,
						),
				}));
				setNoticeLines([]);

				await startStream((signal, onEvent) =>
					client.streamChat(
						{
							conversationId: activeConversationId,
							message,
							parentMessageId: targetMessage.id,
						},
						{ signal, onEvent },
					),
				);
			} catch (editError) {
				setPhase("error");
				setError(
					editError instanceof Error
						? editError.message
						: "Unexpected edit error",
				);
			}
		},
		[
			activeConversationId,
			client,
			startStream,
			streamState.activeRun,
			streamState.messages,
		],
	);

	const handleAction = useCallback(
		async (action: CliInputAction) => {
			if (action.type === "empty") {
				return;
			}

			if (action.type === "quit") {
				abortRef.current?.abort();
				exit();
				return;
			}

			if (action.type === "help") {
				setNoticeLines(helpLines);
				return;
			}

			if (action.type === "sessions") {
				const nextConversations = await refreshConversations();
				setNoticeLines(
					nextConversations.length
						? nextConversations
								.slice(0, 10)
								.map((conversation, index) =>
									formatConversationLabel(conversation, index),
								)
						: ["No conversations yet."],
				);
				return;
			}

			if (action.type === "rename") {
				await renameActiveConversation(action.title);
				return;
			}

			if (action.type === "delete") {
				await deleteActiveConversation();
				return;
			}

			if (action.type === "new") {
				const conversation = await client.createConversation();
				setConversations((items) => [conversation, ...items]);
				await loadConversation(conversation);
				return;
			}

			if (action.type === "switch") {
				const conversation = resolveConversationTarget(
					conversations,
					action.target,
				);
				if (!conversation) {
					setNoticeLines([`No conversation matches ${action.target}.`]);
					return;
				}
				await loadConversation(conversation);
				return;
			}

			if (action.type === "stop") {
				stopStreaming();
				return;
			}

			if (action.type === "approve" || action.type === "reject") {
				await submitApproval(action.type);
				return;
			}

			if (action.type === "regenerate") {
				await regenerateLastAssistantMessage();
				return;
			}

			if (action.type === "edit") {
				await editUserMessageAndRegenerate(action.target, action.message);
				return;
			}

			if (action.type === "unknown") {
				setNoticeLines([`Unknown command ${action.command}. Type /help.`]);
				return;
			}

			await sendMessage(action.message);
		},
		[
			client,
			conversations,
			deleteActiveConversation,
			editUserMessageAndRegenerate,
			exit,
			loadConversation,
			refreshConversations,
			regenerateLastAssistantMessage,
			renameActiveConversation,
			sendMessage,
			stopStreaming,
			submitApproval,
		],
	);

	useInput((typedInput, key) => {
		if (key.ctrl && typedInput === "c") {
			abortRef.current?.abort();
			exit();
			return;
		}

		if (commandSuggestions.length > 0 && (key.downArrow || key.upArrow)) {
			setSelectedCommandIndex((currentIndex) =>
				getNextSlashCommandIndex({
					currentIndex,
					direction: key.downArrow ? "next" : "previous",
					itemCount: commandSuggestions.length,
				}),
			);
			return;
		}

		const returnIndex = typedInput.search(/[\r\n]/);
		if (key.return || returnIndex !== -1) {
			if (
				commandSuggestions.length > 0 &&
				!isExactSlashCommand(input) &&
				selectedCommand
			) {
				setInput(selectedCommand.value);
				setSelectedCommandIndex(0);
				return;
			}

			const submittedInput =
				returnIndex === -1
					? input
					: `${input}${typedInput.slice(0, returnIndex)}`;
			const action = parseCliInput(submittedInput);
			setInput("");
			setSelectedCommandIndex(0);
			void handleAction(action);
			return;
		}

		if (key.backspace || key.delete) {
			setInput((current) => current.slice(0, -1));
			return;
		}

		if (key.ctrl && typedInput === "u") {
			setInput("");
			setSelectedCommandIndex(0);
			return;
		}

		if (typedInput && !key.meta) {
			setInput((current) => `${current}${typedInput}`);
		}
	});

	const visibleMessages = streamState.messages.slice(-12);
	const status = getCliStatus(streamState);

	return (
		<Box flexDirection="column" paddingX={1}>
			<Box>
				<Text color="cyan" bold>
					AI Investment Assistant
				</Text>
				<Text color="gray"> ink cli</Text>
				<Spacer />
				<Text color={phase === "error" ? "red" : "gray"}>{phase}</Text>
			</Box>
			<Box>
				<Text color="gray">api </Text>
				<Text>{apiBase}</Text>
				<Text color="gray"> session </Text>
				<Text>{activeTitle}</Text>
				<Text color="gray"> {status}</Text>
			</Box>
			<Text color="gray">
				────────────────────────────────────────────────────────────────
			</Text>
			{error ? <Text color="red">{error}</Text> : null}
			<NoticePanel lines={noticeLines} />
			{visibleMessages.length === 0 ? (
				<Box marginY={1}>
					<Text color="gray">Type a message. Use /help for commands.</Text>
				</Box>
			) : (
				<Box flexDirection="column" marginTop={1}>
					{visibleMessages.map((message, index) => (
						<ChatMessageView
							displayIndex={
								streamState.messages.length - visibleMessages.length + index + 1
							}
							key={message.id}
							message={message}
						/>
					))}
				</Box>
			)}
			<ApprovalPanel state={streamState} />
			{commandSuggestions.length > 0 ? (
				<Box
					borderColor="cyan"
					borderStyle="round"
					flexDirection="column"
					paddingX={1}
				>
					{commandSuggestions.map((command, index) => (
						<Text
							color={index === selectedCommandOptionIndex ? "cyan" : "gray"}
							key={command.value}
						>
							{index === selectedCommandOptionIndex ? "› " : "  "}
							{command.value} · {command.description}
						</Text>
					))}
				</Box>
			) : null}
			<Box marginTop={1}>
				<Text color="cyan">› </Text>
				<Text>{input}</Text>
				{input ? null : <Text color="gray">message or /command</Text>}
			</Box>
		</Box>
	);
}
