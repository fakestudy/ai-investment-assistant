import { Box, Spacer, Text, useApp, useInput } from "ink";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
	cancelChatStream,
	createConversation,
	listConversations,
	listMessages,
	resumeChatStream,
	streamChat,
	submitApprovalDecisions,
} from "../features/chat/api";
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
	findPendingApprovalBatch,
	getCliStatus,
	parseCliInput,
	projectCliStreamEvent,
} from "./chat-cli-state";

type ChatCliClient = {
	listConversations: typeof listConversations;
	createConversation: typeof createConversation;
	listMessages: typeof listMessages;
	streamChat: typeof streamChat;
	resumeChatStream: typeof resumeChatStream;
	submitApprovalDecisions: typeof submitApprovalDecisions;
	cancelChatStream: typeof cancelChatStream;
};

type RuntimePhase = "booting" | "ready" | "loading" | "streaming" | "error";

const defaultClient: ChatCliClient = {
	listConversations,
	createConversation,
	listMessages,
	streamChat,
	resumeChatStream,
	submitApprovalDecisions,
	cancelChatStream,
};

const helpLines = [
	"/new              start a new conversation",
	"/sessions         list recent conversations",
	"/switch <id|#>    switch by id prefix or list number",
	"/stop             stop the current stream",
	"/approve          approve all pending tool requests",
	"/reject           reject all pending tool requests",
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
			activeRun.status === "resuming" || activeRun.status === "resume_queued"
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

function ChatMessageView({ message }: { message: ChatMessage }) {
	const label = getMessageLabel(message);
	const body = getMessageBody(message);
	const reasoning =
		message.reasoning && message.content
			? trimText(message.reasoning.replace(/\s+/g, " "), 140)
			: undefined;

	return (
		<Box flexDirection="column" marginBottom={1}>
			<Text>
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
		streamState.title ?? activeConversation?.title ?? "No conversation";

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

				setConversations(nextConversations);
				if (nextConversations[0]) {
					await loadConversation(nextConversations[0]);
				} else {
					setPhase("ready");
					setNoticeLines(["No conversations yet. Type a message to start."]);
				}
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
	}, [client, loadConversation]);

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

			if (action.type === "unknown") {
				setNoticeLines([`Unknown command ${action.command}. Type /help.`]);
				return;
			}

			await sendMessage(action.message);
		},
		[
			client,
			conversations,
			exit,
			loadConversation,
			refreshConversations,
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

		const returnIndex = typedInput.search(/[\r\n]/);
		if (key.return || returnIndex !== -1) {
			const submittedInput =
				returnIndex === -1
					? input
					: `${input}${typedInput.slice(0, returnIndex)}`;
			const action = parseCliInput(submittedInput);
			setInput("");
			void handleAction(action);
			return;
		}

		if (key.backspace || key.delete) {
			setInput((current) => current.slice(0, -1));
			return;
		}

		if (key.ctrl && typedInput === "u") {
			setInput("");
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
					{visibleMessages.map((message) => (
						<ChatMessageView key={message.id} message={message} />
					))}
				</Box>
			)}
			<ApprovalPanel state={streamState} />
			<Box marginTop={1}>
				<Text color="cyan">› </Text>
				<Text>{input}</Text>
				{input ? null : <Text color="gray">message or /command</Text>}
			</Box>
		</Box>
	);
}
