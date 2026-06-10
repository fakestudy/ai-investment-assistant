import { reduceChatStreamEvent } from "../features/chat/chat-event-reducer";
import type {
	ApprovalBatch,
	ChatMessage,
	ConversationRunState,
	ReceivedChatStreamEvent,
} from "../features/chat/types";

export type { ApprovalBatch, ChatMessage, ConversationRunState };

export type CliStreamState = {
	messages: ChatMessage[];
	activeRun?: ConversationRunState;
	title?: string;
};

export type CliInputAction =
	| { type: "empty" }
	| { type: "send"; message: string }
	| { type: "new" }
	| { type: "sessions" }
	| { type: "switch"; target: string }
	| { type: "stop" }
	| { type: "approve" }
	| { type: "reject" }
	| { type: "help" }
	| { type: "quit" }
	| { type: "unknown"; command: string };

const commandAliases: Record<string, CliInputAction> = {
	"/new": { type: "new" },
	"/sessions": { type: "sessions" },
	"/stop": { type: "stop" },
	"/approve": { type: "approve" },
	"/reject": { type: "reject" },
	"/help": { type: "help" },
	"/quit": { type: "quit" },
	"/exit": { type: "quit" },
};

export function parseCliInput(input: string): CliInputAction {
	const trimmed = input.trim();

	if (!trimmed) {
		return { type: "empty" };
	}

	if (!trimmed.startsWith("/")) {
		return { type: "send", message: trimmed };
	}

	const [command, ...args] = trimmed.split(/\s+/);
	if (command === "/switch") {
		const target = args.join(" ").trim();
		return target ? { type: "switch", target } : { type: "unknown", command };
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
