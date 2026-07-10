"""Pydantic schemas for meetings."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.constants import FILE_EXTENSION_MAX_LENGTH, FILENAME_MAX_LENGTH, TITLE_MAX_LENGTH
from app.models.enums import ProcessingStatus
from app.schemas.auth import APIResponse


class MeetingBase(BaseModel):
    """Shared meeting fields."""

    title: str = Field(..., min_length=1, max_length=TITLE_MAX_LENGTH)
    original_filename: str = Field(..., min_length=1, max_length=FILENAME_MAX_LENGTH)
    stored_filename: str = Field(..., min_length=1, max_length=FILENAME_MAX_LENGTH)
    file_extension: str = Field(..., min_length=1, max_length=FILE_EXTENSION_MAX_LENGTH)
    file_size: int = Field(..., ge=0)
    duration_seconds: int | None = Field(default=None, ge=0)
    transcript: str | None = None
    executive_summary: str | None = None
    key_points: list[str] | None = None
    key_decisions: list[str] | None = None
    participants: list[str] | None = None
    deadlines: list[dict[str, Any]] | None = None
    risks: list[str] | None = None
    next_steps: list[str] | None = None
    processing_status: ProcessingStatus = ProcessingStatus.UPLOADED


class MeetingCreate(MeetingBase):
    """Fields required to create a meeting record."""

    user_id: int = Field(..., gt=0)


class MeetingUpdate(BaseModel):
    """Fields allowed when updating a meeting record."""

    title: str | None = Field(default=None, min_length=1, max_length=TITLE_MAX_LENGTH)
    original_filename: str | None = Field(default=None, min_length=1, max_length=FILENAME_MAX_LENGTH)
    stored_filename: str | None = Field(default=None, min_length=1, max_length=FILENAME_MAX_LENGTH)
    file_extension: str | None = Field(default=None, min_length=1, max_length=FILE_EXTENSION_MAX_LENGTH)
    file_size: int | None = Field(default=None, ge=0)
    duration_seconds: int | None = Field(default=None, ge=0)
    transcript: str | None = None
    executive_summary: str | None = None
    key_points: list[str] | None = None
    key_decisions: list[str] | None = None
    participants: list[str] | None = None
    deadlines: list[dict[str, Any]] | None = None
    risks: list[str] | None = None
    next_steps: list[str] | None = None
    processing_status: ProcessingStatus | None = None


class MeetingResponse(MeetingBase):
    """Meeting response schema."""

    id: int
    user_id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MeetingUploadRequest(BaseModel):
    """Multipart form fields for meeting upload."""

    title: str = Field(..., min_length=1, max_length=TITLE_MAX_LENGTH)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        """Normalize and validate the meeting title."""
        normalized_value = value.strip()
        if not normalized_value:
            raise ValueError("Meeting title cannot be empty.")
        return normalized_value


class MeetingPublic(BaseModel):
    """Meeting data safe to return to API clients."""

    id: int
    user_id: int
    title: str
    original_filename: str
    file_extension: str
    file_size: int
    duration_seconds: int | None
    transcript: str | None
    executive_summary: str | None
    key_points: list[str] | None
    key_decisions: list[str] | None
    participants: list[str] | None
    deadlines: list[dict[str, Any]] | None
    risks: list[str] | None
    next_steps: list[str] | None
    processing_status: ProcessingStatus
    processing_progress: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MeetingListData(BaseModel):
    """Paginated meeting list data."""

    items: list[MeetingPublic]
    page: int
    page_size: int
    total: int


class MeetingUploadResponse(APIResponse):
    """Meeting upload response envelope."""

    success: bool = True
    data: MeetingPublic


class MeetingDetailResponse(APIResponse):
    """Meeting detail response envelope."""

    success: bool = True
    data: MeetingPublic


class MeetingListResponse(APIResponse):
    """Meeting list response envelope."""

    success: bool = True
    data: MeetingListData


class MeetingProcessData(BaseModel):
    """Meeting processing result data."""

    id: int
    processing_status: ProcessingStatus
    duration_seconds: int | None
    transcript_available: bool


class MeetingProcessResponse(APIResponse):
    """Meeting processing response envelope."""

    success: bool = True
    data: MeetingProcessData


class MeetingTranscriptData(BaseModel):
    """Meeting transcript response data."""

    id: int
    transcript: str
    processing_status: ProcessingStatus


class MeetingTranscriptResponse(APIResponse):
    """Meeting transcript response envelope."""

    success: bool = True
    data: MeetingTranscriptData


class MeetingProcessingStartData(BaseModel):
    """Background processing start response data."""

    id: int
    processing_status: ProcessingStatus
    processing_progress: int


class MeetingProcessingStartResponse(APIResponse):
    """Background processing start response envelope."""

    success: bool = True
    data: MeetingProcessingStartData


class MeetingStatusData(BaseModel):
    """Current meeting processing status data."""

    id: int
    processing_status: ProcessingStatus
    processing_progress: int
    updated_at: datetime


class MeetingStatusResponse(APIResponse):
    """Meeting status response envelope."""

    success: bool = True
    data: MeetingStatusData
