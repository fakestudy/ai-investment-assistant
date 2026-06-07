import type {
	ChatMessage,
	ChatStreamEvent,
	ChatStreamResumeRequest,
	Conversation,
	ConversationMessagesResponse,
	ReceivedChatStreamEvent,
	StreamChatRequest,
	SubmitApprovalDecisionsRequest,
} from "./types";

export const CHAT_API_BASE =
	process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:3000";

type JsonRequestInit = Omit<RequestInit, "body"> & {
	body?: unknown;
};

function buildApiUrl(path: string) {
	return new URL(path, CHAT_API_BASE).toString();
}

function jsonHeaders(headers?: HeadersInit) {
	return {
		"Content-Type": "application/json",
		...headers,
	};
}

export class ChatApiError extends Error {
	status: number;

	constructor(status: number) {
		super(`Request failed with status ${status}`);
		this.name = "ChatApiError";
		this.status = status;
	}
}

async function requestJson<T>(
	path: string,
	init?: JsonRequestInit,
): Promise<T> {
	const response = await fetch(buildApiUrl(path), {
		...init,
		headers: jsonHeaders(init?.headers),
		body: init?.body === undefined ? undefined : JSON.stringify(init.body),
	});

	if (!response.ok) {
		throw new ChatApiError(response.status);
	}

	return response.json() as Promise<T>;
}

async function requestVoid(
	path: string,
	init?: JsonRequestInit,
): Promise<void> {
	const response = await fetch(buildApiUrl(path), {
		...init,
		headers: jsonHeaders(init?.headers),
		body: init?.body === undefined ? undefined : JSON.stringify(init.body),
	});

	if (!response.ok) {
		throw new ChatApiError(response.status);
	}
}

export function listConversations(): Promise<Conversation[]> {
	return requestJson<Conversation[]>("/api/conversations/list");
}

export function createConversation(): Promise<Conversation> {
	return requestJson<Conversation>("/api/conversations", {
		method: "POST",
		body: {},
	});
}

export function renameConversation(
	conversationId: string,
	title: string,
): Promise<Conversation> {
	return requestJson<Conversation>("/api/conversation/title/update", {
		method: "POST",
		body: {
			conversation_id: conversationId,
			title,
		},
	});
}

export async function deleteConversation(
	conversationId: string,
): Promise<void> {
	await requestVoid("/api/conversation/delete", {
		method: "POST",
		body: {
			conversation_id: conversationId,
		},
	});
}

export function listMessages(
	conversationId: string,
): Promise<ConversationMessagesResponse> {
	return requestJson<ConversationMessagesResponse>(
		`/api/conversation/messages/${encodeURIComponent(conversationId)}`,
	);
}

export function editMessage(
	messageId: string,
	content: string,
): Promise<ChatMessage> {
	return requestJson<ChatMessage>(
		`/api/messages/${encodeURIComponent(messageId)}`,
		{
			method: "PATCH",
			body: { content },
		},
	);
}

export async function cancelChatStream(messageId: string): Promise<void> {
	await requestVoid(
		`/api/chat/streams/${encodeURIComponent(messageId)}/cancel`,
		{
			method: "POST",
		},
	);
}

function parseSseEvent(rawEvent: string): ReceivedChatStreamEvent | undefined {
	const lines = rawEvent.split(/\r?\n/);
	const idLine = lines.find((line) => line.startsWith("id:"));
	const parsedEventId = idLine
		? Number.parseInt(idLine.slice("id:".length).trim(), 10)
		: Number.NaN;
	const data = lines
		.filter((line) => line.startsWith("data:"))
		.map((line) => line.slice("data:".length).trimStart())
		.join("\n")
		.trim();

	if (!data || data === "[DONE]") {
		return undefined;
	}

	return {
		eventId: Number.isNaN(parsedEventId) ? undefined : parsedEventId,
		event: JSON.parse(data) as ChatStreamEvent,
	};
}

async function readSseResponse(
	response: Response,
	options: {
		onEvent: (event: ReceivedChatStreamEvent) => void;
	},
): Promise<void> {
	if (!response.body) {
		throw new Error("Stream response body is empty");
	}

	const reader = response.body.getReader();
	const decoder = new TextDecoder();
	let buffer = "";

	while (true) {
		const { done, value } = await reader.read();
		buffer += decoder.decode(value, { stream: !done });

		const events = buffer.split(/\r?\n\r?\n/);
		buffer = events.pop() ?? "";

		for (const rawEvent of events) {
			const event = parseSseEvent(rawEvent);
			if (event) {
				options.onEvent(event);
			}
		}

		if (done) {
			break;
		}
	}

	const event = parseSseEvent(buffer);
	if (event) {
		options.onEvent(event);
	}
}

export async function streamChat(
	request: StreamChatRequest,
	options: {
		signal: AbortSignal;
		onEvent: (event: ReceivedChatStreamEvent) => void;
	},
): Promise<void> {
	const response = await fetch(buildApiUrl("/api/chat/stream"), {
		method: "POST",
		headers: jsonHeaders(),
		body: JSON.stringify(request),
		signal: options.signal,
	});

	if (!response.ok) {
		throw new ChatApiError(response.status);
	}

	await readSseResponse(response, options);
}

export async function resumeChatStream(
	request: ChatStreamResumeRequest,
	options: {
		signal: AbortSignal;
		onEvent: (event: ReceivedChatStreamEvent) => void;
	},
): Promise<void> {
	const response = await fetch(buildApiUrl("/api/chat/stream/resume"), {
		method: "POST",
		headers: jsonHeaders(),
		body: JSON.stringify(request),
		signal: options.signal,
	});

	if (!response.ok) {
		throw new ChatApiError(response.status);
	}

	await readSseResponse(response, options);
}

export async function submitApprovalDecisions(
	batchId: string,
	request: SubmitApprovalDecisionsRequest,
	options: {
		signal: AbortSignal;
		onEvent: (event: ReceivedChatStreamEvent) => void;
	},
): Promise<void> {
	const response = await fetch(
		buildApiUrl(`/api/chat/approval/decisions/${encodeURIComponent(batchId)}`),
		{
			method: "POST",
			headers: jsonHeaders(),
			body: JSON.stringify({
				decisions: request.decisions,
				afterEventId: request.afterEventId,
			}),
			signal: options.signal,
		},
	);

	if (!response.ok) {
		throw new ChatApiError(response.status);
	}

	await readSseResponse(response, options);
}
