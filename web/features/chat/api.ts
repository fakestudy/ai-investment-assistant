import type {
	ChatMessage,
	ChatStreamEvent,
	Conversation,
	StreamChatRequest,
} from "./types";

export const CHAT_API_BASE =
	process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8080";

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
		throw new Error(`Request failed with status ${response.status}`);
	}

	return response.json() as Promise<T>;
}

async function requestVoid(path: string, init?: RequestInit): Promise<void> {
	const response = await fetch(buildApiUrl(path), {
		...init,
		headers: jsonHeaders(init?.headers),
	});

	if (!response.ok) {
		throw new Error(`Request failed with status ${response.status}`);
	}
}

export function listConversations(): Promise<Conversation[]> {
	return requestJson<Conversation[]>("/api/conversations");
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
	return requestJson<Conversation>(
		`/api/conversations/${encodeURIComponent(conversationId)}`,
		{
			method: "PATCH",
			body: { title },
		},
	);
}

export async function deleteConversation(
	conversationId: string,
): Promise<void> {
	await requestVoid(
		`/api/conversations/${encodeURIComponent(conversationId)}`,
		{
			method: "DELETE",
		},
	);
}

export function listMessages(conversationId: string): Promise<ChatMessage[]> {
	return requestJson<ChatMessage[]>(
		`/api/conversations/${encodeURIComponent(conversationId)}/messages`,
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

function parseSseEvent(rawEvent: string): ChatStreamEvent | undefined {
	const data = rawEvent
		.split(/\r?\n/)
		.filter((line) => line.startsWith("data:"))
		.map((line) => line.slice("data:".length).trimStart())
		.join("\n")
		.trim();

	if (!data || data === "[DONE]") {
		return undefined;
	}

	return JSON.parse(data) as ChatStreamEvent;
}

export async function streamChat(
	request: StreamChatRequest,
	options: {
		signal: AbortSignal;
		onEvent: (event: ChatStreamEvent) => void;
	},
): Promise<void> {
	const response = await fetch(buildApiUrl("/api/chat/stream"), {
		method: "POST",
		headers: jsonHeaders(),
		body: JSON.stringify(request),
		signal: options.signal,
	});

	if (!response.ok) {
		throw new Error(`Request failed with status ${response.status}`);
	}

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
