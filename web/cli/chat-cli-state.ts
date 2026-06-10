import { reduceChatStreamEvent } from "../features/chat/chat-event-reducer";
import { isExactSlashCommand } from "../features/chat/slash-commands";
import type {
	ApprovalBatch,
	ChatMessage,
	Conversation,
	ConversationRunState,
	ReceivedChatStreamEvent,
} from "../features/chat/types";

export type { ApprovalBatch, ChatMessage, Conversation, ConversationRunState };

export type CliStreamState = {
	messages: ChatMessage[];
	activeRun?: ConversationRunState;
	title?: string;
};

export type CliBootState = {
	conversations: Conversation[];
	activeConversationId?: string;
	streamState: CliStreamState;
	noticeLines: string[];
};

export type CliInputAction =
	| { type: "empty" }
	| { type: "send"; message: string }
	| { type: "new" }
	| { type: "sessions" }
	| { type: "switch"; target: string }
	| { type: "rename"; title: string }
	| { type: "delete" }
	| { type: "stop" }
	| { type: "approve" }
	| { type: "reject" }
	| { type: "regenerate" }
	| { type: "edit"; target: string; message: string }
	| { type: "help" }
	| { type: "quit" }
	| { type: "unknown"; command: string };

const commandAliases: Record<string, CliInputAction> = {
	"/new": { type: "new" },
	"/sessions": { type: "sessions" },
	"/delete": { type: "delete" },
	"/stop": { type: "stop" },
	"/approve": { type: "approve" },
	"/reject": { type: "reject" },
	"/regenerate": { type: "regenerate" },
	"/help": { type: "help" },
	"/quit": { type: "quit" },
	"/exit": { type: "quit" },
};

export function createFreshCliBootState(
	conversations: Conversation[],
): CliBootState {
	return {
		conversations,
		activeConversationId: undefined,
		streamState: { messages: [] },
		noticeLines: conversations.length
			? ["New chat ready. Use /sessions to view history."]
			: ["New chat ready. Type a message to start."],
	};
}

export function parseCliInput(input: string): CliInputAction {
	const trimmed = input.trim();

	if (!trimmed) {
		return { type: "empty" };
	}

	if (!trimmed.startsWith("/")) {
		return { type: "send", message: trimmed };
	}

	const [command, ...args] = trimmed.split(/\s+/);
	if (isExactSlashCommand(trimmed)) {
		return { type: "send", message: trimmed };
	}

	if (command === "/switch") {
		const target = args.join(" ").trim();
		return target ? { type: "switch", target } : { type: "unknown", command };
	}

	if (command === "/rename") {
		const title = args.join(" ").trim();
		return title ? { type: "rename", title } : { type: "unknown", command };
	}

	if (command === "/edit") {
		const [target, ...messageParts] = args;
		const message = messageParts.join(" ").trim();
		return target && message
			? { type: "edit", target, message }
			: { type: "unknown", command };
	}

	return commandAliases[command] ?? { type: "unknown", command };
}

export function projectCliStreamEvent(
	state: CliStreamState,
	received: ReceivedChatStreamEvent,
): CliStreamState {
	const projected = reduceChatStreamEvent(
		{ messages: state.messages, activeRun: state.activeRun },
		received,
	);

	return {
		...state,
		messages: projected.messages,
		activeRun: projected.activeRun,
		title: received.event.type === "title" ? received.event.title : state.title,
	};
}

export function findPendingApprovalBatch(
	state: CliStreamState,
): ApprovalBatch | undefined {
	if (state.activeRun?.approvalBatch?.status === "pending") {
		return state.activeRun.approvalBatch;
	}

	for (const message of state.messages) {
		for (const part of message.timelineParts ?? []) {
			if (part.type === "approval" && part.batch.status === "pending") {
				return part.batch;
			}
		}
	}

	return undefined;
}

export function getCliStatus(state: CliStreamState): string {
	const pendingApproval = findPendingApprovalBatch(state);
	if (pendingApproval) {
		const count = pendingApproval.requests.length;
		return `awaiting approval: ${count} tool ${count === 1 ? "request" : "requests"}`;
	}

	if (!state.activeRun) {
		return "idle";
	}

	if (state.activeRun.status === "resuming") {
		return "resuming";
	}

	return "streaming";
}
