from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ApprovalDecision = Literal["pending", "approved", "rejected", "expired"]
ApprovalSubmissionDecision = Literal["approve", "reject"]
RunStatus = Literal[
    "queued",
    "running",
    "awaiting_approval",
    "resume_queued",
    "resuming",
    "completed",
    "failed",
]


class FrontendModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class ToolInvocation(FrontendModel):
    id: str
    message_id: str = Field(alias="messageId")
    tool_name: str = Field(alias="toolName")
    args: dict[str, Any]
    result: Any | None = None
    error: str | None = None
    latency_ms: int | None = Field(default=None, alias="latencyMs")
    status: Literal[
        "running",
        "completed",
        "error",
        "awaiting_approval",
        "rejected",
        "expired",
    ]
    created_at: str | None = Field(default=None, alias="createdAt")


class ApprovalRequestPayload(FrontendModel):
    id: str
    tool_invocation_id: str = Field(alias="toolInvocationId")
    tool_name: str = Field(alias="toolName")
    args: dict[str, Any]
    decision: ApprovalDecision
    decided_at: str | None = Field(default=None, alias="decidedAt")


class ApprovalBatchPayload(FrontendModel):
    id: str
    status: Literal["pending", "resolved", "expired"]
    expires_at: str = Field(alias="expiresAt")
    requests: list[ApprovalRequestPayload]
    resolution_source: Literal["manual", "timeout"] | None = Field(
        default=None,
        alias="resolutionSource",
    )
    resolved_at: str | None = Field(default=None, alias="resolvedAt")


class ReasoningTimelinePart(FrontendModel):
    id: str
    type: Literal["reasoning"]
    order_index: int | None = Field(default=None, alias="orderIndex")
    text: str


class ToolTimelinePart(FrontendModel):
    id: str
    type: Literal["tool"]
    order_index: int | None = Field(default=None, alias="orderIndex")
    invocation: ToolInvocation


class ApprovalTimelinePart(FrontendModel):
    id: str
    type: Literal["approval"]
    order_index: int | None = Field(default=None, alias="orderIndex")
    batch: ApprovalBatchPayload


ChatTimelinePart = Annotated[
    ReasoningTimelinePart | ToolTimelinePart | ApprovalTimelinePart,
    Field(discriminator="type"),
]


class ChatMessage(FrontendModel):
    id: str
    conversation_id: str = Field(alias="conversationId")
    role: Literal["user", "assistant", "tool"]
    content: str
    reasoning: str | None = None
    tool_invocations: list[ToolInvocation] | None = Field(
        default=None,
        alias="toolInvocations",
    )
    timeline_parts: list[ChatTimelinePart] | None = Field(
        default=None,
        alias="timelineParts",
    )
    status: Literal["idle", "streaming", "done", "error"] | None = None
    created_at: str = Field(alias="createdAt")


class ActiveRunSummary(FrontendModel):
    run_id: str = Field(alias="runId")
    status: RunStatus
    last_event_id: int | None = Field(default=None, alias="lastEventId")
    assistant_message_id: str = Field(alias="assistantMessageId")
    approval_batch: ApprovalBatchPayload | None = Field(
        default=None,
        alias="approvalBatch",
    )


class ConversationMessagesResponse(FrontendModel):
    messages: list[ChatMessage]
    active_run: ActiveRunSummary | None = Field(default=None, alias="activeRun")


class RunCreatedEvent(FrontendModel):
    type: Literal["run_created"]
    run_id: str = Field(alias="runId")
    status: RunStatus
    assistant_message_id: str = Field(alias="assistantMessageId")


class MessageCreatedEvent(FrontendModel):
    type: Literal["message_created"]
    message: ChatMessage


class DeltaEvent(FrontendModel):
    type: Literal["delta"]
    message_id: str = Field(alias="messageId")
    text: str


class ReasoningEvent(FrontendModel):
    type: Literal["reasoning"]
    message_id: str = Field(alias="messageId")
    text: str


class ToolCallEvent(FrontendModel):
    type: Literal["tool_call"]
    message_id: str = Field(alias="messageId")
    invocation: ToolInvocation


class ToolResultEvent(FrontendModel):
    type: Literal["tool_result"]
    message_id: str = Field(alias="messageId")
    invocation: ToolInvocation


class TitleEvent(FrontendModel):
    type: Literal["title"]
    conversation_id: str = Field(alias="conversationId")
    title: str


class DoneEvent(FrontendModel):
    type: Literal["done"]
    message_id: str = Field(alias="messageId")


class ErrorEvent(FrontendModel):
    type: Literal["error"]
    message_id: str | None = Field(default=None, alias="messageId")
    message: str


class ApprovalRequiredEvent(FrontendModel):
    type: Literal["approval_required"]
    run_id: str = Field(alias="runId")
    message_id: str = Field(alias="messageId")
    part: ApprovalTimelinePart


class ApprovalResolvedEvent(FrontendModel):
    type: Literal["approval_resolved"]
    run_id: str = Field(alias="runId")
    batch: ApprovalBatchPayload

    @field_validator("batch")
    @classmethod
    def batch_must_be_resolved(cls, batch: ApprovalBatchPayload) -> ApprovalBatchPayload:
        if batch.status == "pending":
            raise ValueError("approval_resolved requires a resolved or expired batch")
        return batch


class ChatStreamRequest(BaseModel):
    conversation_id: str = Field(alias="conversationId")
    message: str
    generate_title: bool = Field(default=False, alias="generateTitle")
    parent_message_id: str | None = Field(default=None, alias="parentMessageId")
    regenerate_from_message_id: str | None = Field(
        default=None,
        alias="regenerateFromMessageId",
    )


class ChatStreamResumeRequest(FrontendModel):
    run_id: str = Field(alias="runId")
    after_event_id: int = Field(alias="afterEventId")


class ApprovalDecisionItem(FrontendModel):
    approval_request_id: str = Field(alias="approvalRequestId")
    decision: ApprovalSubmissionDecision


class ApprovalDecisionRequest(FrontendModel):
    decisions: list[ApprovalDecisionItem]
    after_event_id: int = Field(alias="afterEventId")


ChatStreamResponse = Annotated[
    RunCreatedEvent
    | MessageCreatedEvent
    | DeltaEvent
    | ReasoningEvent
    | ToolCallEvent
    | ToolResultEvent
    | TitleEvent
    | DoneEvent
    | ErrorEvent
    | ApprovalRequiredEvent
    | ApprovalResolvedEvent,
    Field(discriminator="type"),
]
