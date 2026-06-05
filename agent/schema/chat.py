from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


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
    status: Literal["running", "completed", "error"]
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


class ChatStreamRequest(BaseModel):
    conversation_id: str = Field(alias="conversationId")
    message: str
    generate_title: bool = Field(default=False, alias="generateTitle")
    parent_message_id: str | None = Field(default=None, alias="parentMessageId")
    regenerate_from_message_id: str | None = Field(
        default=None,
        alias="regenerateFromMessageId",
    )


ChatStreamResponse = Annotated[
    MessageCreatedEvent
    | DeltaEvent
    | ReasoningEvent
    | ToolCallEvent
    | ToolResultEvent
    | TitleEvent
    | DoneEvent
    | ErrorEvent,
    Field(discriminator="type"),
]
