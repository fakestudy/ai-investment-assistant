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

export type ToolApprovalState = {
	batchId: string;
	requestId: string;
	status: ApprovalBatch["status"];
	decision: ApprovalDecision;
	expiresAt?: string;
	decidedAt?: string;
};

export type RunTimelineItem =
	| {
			id: string;
			type: "thought";
			orderIndex?: number;
			text: string;
	  }
	| {
			id: string;
			type: "tool";
			orderIndex?: number;
			invocation: ToolInvocation;
			approval?: ToolApprovalState;
	  };

export type ChatMessage = {
	id: string;
	conversationId: string;
	role: ChatRole;
	content: string;
	reasoning?: string;
	toolInvocations?: ToolInvocation[];
	timelineParts?: ChatTimelinePart[];
	timelineItems?: RunTimelineItem[];
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

export type ConversationRunState = {
	runId: string;
	assistantMessageId: string;
	status: "streaming" | "awaiting_approval" | "resuming";
	lastEventId?: number;
	approvalBatch?: ApprovalBatch;
};

export type ApprovalDecisionRequest = {
	approvalRequestId: string;
	decision: "approve" | "reject";
};

export type SubmitApprovalDecisionsRequest = {
	decisions: ApprovalDecisionRequest[];
	afterEventId: number;
};

export type ChatStreamEvent =
	| {
			type: "run_created";
			runId: string;
			status: RunStatus;
			assistantMessageId: string;
	  }
	| { type: "message_created"; runId: string; message: ChatMessage }
	| { type: "delta"; runId: string; messageId: string; text: string }
	| { type: "reasoning"; runId: string; messageId: string; text: string }
	| {
			type: "tool_call";
			runId: string;
			messageId: string;
			invocation: ToolInvocation;
	  }
	| {
			type: "tool_result";
			runId: string;
			messageId: string;
			invocation: ToolInvocation;
	  }
	| { type: "title"; runId: string; conversationId: string; title: string }
	| { type: "done"; runId: string; messageId: string }
	| { type: "error"; runId: string; messageId?: string; message: string }
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

export type ReceivedChatStreamEvent = {
	eventId?: number;
	event: ChatStreamEvent;
};

export type ChatError = {
	message: string;
	scope: "conversation" | "message" | "stream";
};
