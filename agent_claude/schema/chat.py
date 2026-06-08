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
