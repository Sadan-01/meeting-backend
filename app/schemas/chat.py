"""Pydantic schemas for meeting chat history."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.auth import APIResponse


class ChatHistoryBase(BaseModel):
    """Shared chat history fields."""

    question: str = Field(..., min_length=1)
    answer: str = Field(..., min_length=1)


class ChatHistoryCreate(ChatHistoryBase):
    """Fields required to create a chat history record."""

    meeting_id: int = Field(..., gt=0)


class ChatHistoryUpdate(BaseModel):
    """Fields allowed when updating a chat history record."""

    question: str | None = Field(default=None, min_length=1)
    answer: str | None = Field(default=None, min_length=1)


class ChatHistoryResponse(ChatHistoryBase):
    """Chat history response schema."""

    id: int
    meeting_id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ChatRequest(BaseModel):
    """Request payload for meeting chat."""

    message: str = Field(..., min_length=1, max_length=4000)

    @field_validator("message")
    @classmethod
    def normalize_message(cls, value: str) -> str:
        """Trim and validate a chat message."""
        normalized_value = value.strip()
        if not normalized_value:
            raise ValueError("Message cannot be empty.")
        return normalized_value


class ChatAnswerData(BaseModel):
    """AI answer returned for a meeting chat question."""

    answer: str


class ChatAnswerResponse(APIResponse):
    """Meeting chat response envelope."""

    success: bool = True
    data: ChatAnswerData


class ChatHistoryListData(BaseModel):
    """Conversation history response data."""

    items: list[ChatHistoryResponse]


class ChatHistoryListResponse(APIResponse):
    """Conversation history response envelope."""

    success: bool = True
    data: ChatHistoryListData
