from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ChatConversation(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    title: str
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
