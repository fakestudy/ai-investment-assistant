export type ChatRole = "user" | "assistant" | "tool";

export type Conversation = {
	id: string;
	title: string;
	createdAt: string;
	updatedAt: string;
};

export type MessageStatus = "idle" | "streaming" | "done" | "error";
export type ToolInvocationStatus = "running" | "completed" | "error";
export type ToolName = "web_search" | "fetch_url" | (string & {});

export type ToolInvocation = {
	id: string;
	messageId: string;
	toolName: ToolName;
	args: Record<string, unknown>;
	result?: unknown;
	error?: string;
	latencyMs?: number;
	status: ToolInvocationStatus;
	createdAt?: string;
};

export type ChatMessage = {
	id: string;
	conversationId: string;
	role: ChatRole;
	content: string;
	reasoning?: string;
	toolInvocations?: ToolInvocation[];
	status?: MessageStatus;
	createdAt: string;
};

export type StreamChatRequest = {
	conversationId: string;
	message: string;
	parentMessageId?: string;
	regenerateFromMessageId?: string;
};

export type ChatStreamEvent =
	| { type: "message_created"; message: ChatMessage }
	| { type: "delta"; messageId: string; text: string }
	| { type: "reasoning"; messageId: string; text: string }
	| { type: "tool_call"; messageId: string; invocation: ToolInvocation }
	| { type: "tool_result"; messageId: string; invocation: ToolInvocation }
	| { type: "title"; conversationId: string; title: string }
	| { type: "done"; messageId: string }
	| { type: "error"; messageId?: string; message: string };

export type ChatError = {
	message: string;
	scope: "conversation" | "message" | "stream";
};
