from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ChatConversation(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: str
    title: str
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class UpdateConversationTitleRequest(BaseModel):
    conversation_id: str
    title: str


class DeleteConversationRequest(BaseModel):
    conversation_id: str


class DeleteConversationResponse(BaseModel):
    conversation_id: str
    deleted: bool
