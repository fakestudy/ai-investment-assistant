from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class FrontendModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)


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


ChatTimelinePart = Annotated[
    ReasoningTimelinePart | ToolTimelinePart,
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


class ConversationMessagesResponse(FrontendModel):
    messages: list[ChatMessage]
    active_run: None = Field(default=None, alias="activeRun")


class StreamChatRequest(FrontendModel):
    conversation_id: str = Field(alias="conversationId")
    message: str
    generate_title: bool | None = Field(default=None, alias="generateTitle")
    parent_message_id: str | None = Field(default=None, alias="parentMessageId")
    regenerate_from_message_id: str | None = Field(
        default=None,
        alias="regenerateFromMessageId",
    )


class ChatStreamEventBase(FrontendModel):
    run_id: str = Field(alias="runId")


class MessageCreatedEvent(ChatStreamEventBase):
    type: Literal["message_created"]
    message: ChatMessage


class ReasoningEvent(ChatStreamEventBase):
    type: Literal["reasoning"]
    message_id: str = Field(alias="messageId")
    text: str


class DeltaEvent(ChatStreamEventBase):
    type: Literal["delta"]
    message_id: str = Field(alias="messageId")
    text: str


class DoneEvent(ChatStreamEventBase):
    type: Literal["done"]
    message_id: str = Field(alias="messageId")


class ErrorEvent(ChatStreamEventBase):
    type: Literal["error"]
    message_id: str | None = Field(default=None, alias="messageId")
    message: str


class ToolCallEvent(ChatStreamEventBase):
    type: Literal["tool_call"]
    message_id: str = Field(alias="messageId")
    invocation: ToolInvocation


class ToolResultEvent(ChatStreamEventBase):
    type: Literal["tool_result"]
    message_id: str = Field(alias="messageId")
    invocation: ToolInvocation


class TitleEvent(ChatStreamEventBase):
    type: Literal["title"]
    conversation_id: str = Field(alias="conversationId")
    title: str


ChatStreamEvent = Annotated[
    MessageCreatedEvent
    | ReasoningEvent
    | DeltaEvent
    | DoneEvent
    | ErrorEvent
    | ToolCallEvent
    | ToolResultEvent
    | TitleEvent,
    Field(discriminator="type"),
]
