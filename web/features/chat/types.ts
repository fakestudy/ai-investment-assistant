export type ChatRole = "user" | "assistant" | "tool";

export type Conversation = {
	id: string;
	title: string;
	createdAt: string;
	updatedAt: string;
};

export type MessageStatus = "idle" | "streaming" | "done" | "error";
export type ToolInvocationStatus =
	| "running"
	| "completed"
	| "error"
	| "awaiting_approval"
	| "rejected"
	| "expired";
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

export type ApprovalDecision = "pending" | "approved" | "rejected" | "expired";

export type ApprovalRequest = {
	id: string;
	toolInvocationId: string;
	toolName: ToolName;
	args: Record<string, unknown>;
	decision: ApprovalDecision;
	decidedAt?: string;
};

export type ApprovalBatch = {
	id: string;
	status: "pending" | "resolved" | "expired";
	expiresAt: string;
	requests: ApprovalRequest[];
	resolutionSource?: "manual" | "timeout";
	resolvedAt?: string;
};

export type ChatTimelinePart =
	| {
			id: string;
			type: "reasoning";
			orderIndex?: number;
			text: string;
	  }
	| {
			id: string;
			type: "tool";
			orderIndex?: number;
			invocation: ToolInvocation;
	  }
	| {
			id: string;
			type: "approval";
			orderIndex?: number;
			batch: ApprovalBatch;
	  };

export type ChatMessage = {
	id: string;
	conversationId: string;
	role: ChatRole;
	content: string;
	reasoning?: string;
	toolInvocations?: ToolInvocation[];
	timelineParts?: ChatTimelinePart[];
	status?: MessageStatus;
	createdAt: string;
};

export type ActiveRunSummary = {
	runId: string;
	status: RunStatus;
	lastEventId?: number | null;
	assistantMessageId: string;
	approvalBatch?: ApprovalBatch | null;
};

export type RunStatus =
	| "queued"
	| "running"
	| "awaiting_approval"
	| "resume_queued"
	| "resuming"
	| "completed"
	| "failed";

export type ConversationMessagesResponse = {
	messages: ChatMessage[];
	activeRun?: ActiveRunSummary | null;
};

export type StreamChatRequest = {
	conversationId: string;
	message: string;
	generateTitle?: boolean;
	parentMessageId?: string;
	regenerateFromMessageId?: string;
};

export type ChatStreamResumeRequest = {
	runId: string;
	afterEventId: number;
};

export type ChatStreamEvent =
	| {
			type: "run_created";
			runId: string;
			status: RunStatus;
			assistantMessageId: string;
	  }
	| { type: "message_created"; message: ChatMessage }
	| { type: "delta"; messageId: string; text: string }
	| { type: "reasoning"; messageId: string; text: string }
	| { type: "tool_call"; messageId: string; invocation: ToolInvocation }
	| { type: "tool_result"; messageId: string; invocation: ToolInvocation }
	| { type: "title"; conversationId: string; title: string }
	| { type: "done"; messageId: string }
	| { type: "error"; messageId?: string; message: string }
	| {
			type: "approval_required";
			runId: string;
			messageId: string;
			part: Extract<ChatTimelinePart, { type: "approval" }>;
	  }
	| {
			type: "approval_resolved";
			runId: string;
			batch: ApprovalBatch;
	  };

export type ChatError = {
	message: string;
	scope: "conversation" | "message" | "stream";
};
