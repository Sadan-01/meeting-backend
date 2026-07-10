"""Pydantic schemas for action items."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.constants import ASSIGNEE_MAX_LENGTH


class ActionItemBase(BaseModel):
    """Shared action item fields."""

    task: str = Field(..., min_length=1)
    assignee: str | None = Field(default=None, min_length=1, max_length=ASSIGNEE_MAX_LENGTH)
    deadline: datetime | None = None
    completed: bool = False


class ActionItemCreate(ActionItemBase):
    """Fields required to create an action item."""

    meeting_id: int = Field(..., gt=0)


class ActionItemUpdate(BaseModel):
    """Fields allowed when updating an action item."""

    task: str | None = Field(default=None, min_length=1)
    assignee: str | None = Field(default=None, min_length=1, max_length=ASSIGNEE_MAX_LENGTH)
    deadline: datetime | None = None
    completed: bool | None = None


class ActionItemResponse(ActionItemBase):
    """Action item response schema."""

    id: int
    meeting_id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
