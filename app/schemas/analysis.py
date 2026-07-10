"""Pydantic schemas for meeting transcript analysis."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import ProcessingStatus
from app.schemas.auth import APIResponse


class AnalysisActionItem(BaseModel):
    """Structured action item returned by transcript analysis."""

    task: str = Field(..., min_length=1)
    assignee: str | None = None
    deadline: str | None = None


class AnalysisDeadline(BaseModel):
    """Structured deadline returned by transcript analysis."""

    item: str = Field(..., min_length=1)
    deadline: str | None = None
    owner: str | None = None


class AnalysisResult(BaseModel):
    """Structured meeting intelligence extracted from a transcript."""

    executive_summary: str = ""
    key_points: list[str] = Field(default_factory=list)
    action_items: list[AnalysisActionItem] = Field(default_factory=list)
    participants: list[str] = Field(default_factory=list)
    key_decisions: list[str] = Field(default_factory=list)
    deadlines: list[AnalysisDeadline] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)


class SummaryActionItem(BaseModel):
    """Action item exposed in summary responses."""

    id: int
    task: str
    assignee: str | None
    deadline: datetime | None
    completed: bool


class MeetingSummaryData(BaseModel):
    """Stored meeting intelligence returned to clients."""

    id: int
    processing_status: ProcessingStatus
    executive_summary: str | None
    key_points: list[str] | None
    action_items: list[SummaryActionItem]
    participants: list[str] | None
    key_decisions: list[str] | None
    deadlines: list[dict[str, str | None]] | None
    risks: list[str] | None
    next_steps: list[str] | None


class MeetingAnalysisResponse(APIResponse):
    """Meeting analysis response envelope."""

    success: bool = True
    data: MeetingSummaryData


class MeetingSummaryResponse(APIResponse):
    """Meeting summary response envelope."""

    success: bool = True
    data: MeetingSummaryData
