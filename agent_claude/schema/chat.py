from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


class FrontendModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)


class ChatConversation(FrontendModel):
    id: str
    title: str
    created_at: str = Field(alias="createdAt")
    updated_at: str = Field(alias="updatedAt")


class UpdateConversationTitleRequest(BaseModel):
    conversation_id: str
    title: str


class DeleteConversationRequest(BaseModel):
    conversation_id: str


class DeleteConversationResponse(FrontendModel):
    conversation_id: str = Field(alias="conversationId")
    deleted: bool


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


class ApprovalRequestSummary(FrontendModel):
    id: str
    tool_invocation_id: str = Field(alias="toolInvocationId")
    tool_name: str = Field(alias="toolName")
    args: dict[str, Any]
    decision: Literal["pending", "approved", "rejected", "expired"]
    decided_at: str | None = Field(default=None, alias="decidedAt")


class ApprovalBatch(FrontendModel):
    id: str
    status: Literal["pending", "resolved", "expired"]
    expires_at: str | None = Field(default=None, alias="expiresAt")
    requests: list[ApprovalRequestSummary] = Field(default_factory=list)
    resolution_source: str | None = Field(default=None, alias="resolutionSource")
    resolved_at: str | None = Field(default=None, alias="resolvedAt")


class ApprovalTimelinePart(FrontendModel):
    id: str
    type: Literal["approval"]
    order_index: int | None = Field(default=None, alias="orderIndex")
    batch: ApprovalBatch


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
    tool_invocations: list[ToolInvocation] = Field(
        default_factory=list,
        alias="toolInvocations",
    )
    timeline_parts: list[ChatTimelinePart] = Field(
        default_factory=list,
        alias="timelineParts",
    )
    status: Literal["idle", "streaming", "done", "error"] | None = None
    created_at: str = Field(alias="createdAt")


class StreamChatRequest(FrontendModel):
    conversation_id: str = Field(alias="conversationId")
    message: str
    generate_title: bool | None = Field(default=None, alias="generateTitle")
    parent_message_id: str | None = Field(default=None, alias="parentMessageId")
    regenerate_from_message_id: str | None = Field(
        default=None,
        alias="regenerateFromMessageId",
    )


class ActiveRunSummary(FrontendModel):
    run_id: str = Field(alias="runId")
    status: Literal[
        "queued",
        "running",
        "awaiting_approval",
        "resume_queued",
        "resuming",
        "completed",
        "failed",
    ]
    last_event_id: int | None = Field(default=None, alias="lastEventId")
    assistant_message_id: str = Field(alias="assistantMessageId")
    approval_batch: ApprovalBatch | None = Field(default=None, alias="approvalBatch")


class ConversationMessagesResponse(FrontendModel):
    messages: list[ChatMessage]
    active_run: ActiveRunSummary | None = Field(default=None, alias="activeRun")


class ChatStreamResumeRequest(FrontendModel):
    run_id: str = Field(alias="runId")
    after_event_id: int = Field(alias="afterEventId")


class EditMessageRequest(FrontendModel):
    content: str


class ApprovalDecision(FrontendModel):
    approval_request_id: str = Field(alias="approvalRequestId")
    decision: Literal["approve", "reject"]


class ApprovalDecisionsRequest(FrontendModel):
    decisions: list[ApprovalDecision]
    after_event_id: int = Field(alias="afterEventId")


class RunCreatedEvent(FrontendModel):
    type: Literal["run_created"]
    run_id: str = Field(alias="runId")
    conversation_id: str = Field(alias="conversationId")
    assistant_message_id: str = Field(alias="assistantMessageId")
    status: Literal["running"]


class MessageCreatedEvent(FrontendModel):
    type: Literal["message_created"]
    run_id: str | None = Field(default=None, alias="runId")
    message: ChatMessage


class ReasoningEvent(FrontendModel):
    type: Literal["reasoning"]
    run_id: str | None = Field(default=None, alias="runId")
    message_id: str = Field(alias="messageId")
    text: str


class DeltaEvent(FrontendModel):
    type: Literal["delta"]
    run_id: str | None = Field(default=None, alias="runId")
    message_id: str = Field(alias="messageId")
    text: str


class DoneEvent(FrontendModel):
    type: Literal["done"]
    run_id: str | None = Field(default=None, alias="runId")
    message_id: str = Field(alias="messageId")


class ErrorEvent(FrontendModel):
    type: Literal["error"]
    run_id: str | None = Field(default=None, alias="runId")
    message_id: str | None = Field(default=None, alias="messageId")
    message: str


class ToolCallEvent(FrontendModel):
    type: Literal["tool_call"]
    run_id: str | None = Field(default=None, alias="runId")
    message_id: str = Field(alias="messageId")
    invocation: ToolInvocation


class ToolResultEvent(FrontendModel):
    type: Literal["tool_result"]
    run_id: str | None = Field(default=None, alias="runId")
    message_id: str = Field(alias="messageId")
    invocation: ToolInvocation


class TitleEvent(FrontendModel):
    type: Literal["title"]
    run_id: str | None = Field(default=None, alias="runId")
    conversation_id: str = Field(alias="conversationId")
    title: str


class ApprovalRequiredEvent(FrontendModel):
    type: Literal["approval_required"]
    run_id: str = Field(alias="runId")
    message_id: str = Field(alias="messageId")
    part: ApprovalTimelinePart
    approval_batch: ApprovalBatch | None = Field(default=None, alias="approvalBatch")


class ApprovalResolvedEvent(FrontendModel):
    type: Literal["approval_resolved"]
    run_id: str = Field(alias="runId")
    message_id: str | None = Field(default=None, alias="messageId")
    batch: ApprovalBatch
    approval_batch: ApprovalBatch | None = Field(default=None, alias="approvalBatch")


ChatStreamResponse = Annotated[
    RunCreatedEvent
    | MessageCreatedEvent
    | ReasoningEvent
    | DeltaEvent
    | DoneEvent
    | ErrorEvent
    | ToolCallEvent
    | ToolResultEvent
    | TitleEvent
    | ApprovalRequiredEvent
    | ApprovalResolvedEvent,
    Field(discriminator="type"),
]

ChatStreamEvent = ChatStreamResponse
ChatStreamEventAdapter = TypeAdapter(ChatStreamEvent)
