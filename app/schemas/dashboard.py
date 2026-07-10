"""Pydantic schemas for dashboard and analytics APIs."""

from datetime import date, datetime

from pydantic import BaseModel, Field

from app.models.enums import ProcessingStatus
from app.schemas.auth import APIResponse


class DashboardRecentMeeting(BaseModel):
    """Compact meeting data for dashboard lists."""

    id: int
    title: str
    upload_date: datetime
    processing_status: ProcessingStatus
    duration_seconds: int | None
    file_type: str
    has_transcript: bool
    has_summary: bool
    processing_progress: int


class DashboardOverviewData(BaseModel):
    """Dashboard overview statistics."""

    total_meetings: int
    completed_meetings: int
    processing_meetings: int
    queued_meetings: int
    failed_meetings: int
    meetings_uploaded_today: int
    meetings_uploaded_this_week: int
    meetings_uploaded_this_month: int
    average_meeting_duration: float | None
    average_processing_time: float | None
    total_transcript_size: int
    total_storage_used: int
    recent_meetings: list[DashboardRecentMeeting]
    processing_progress: list[DashboardRecentMeeting]


class DashboardOverviewResponse(APIResponse):
    """Dashboard overview response envelope."""

    success: bool = True
    data: DashboardOverviewData


class DashboardRecentResponse(APIResponse):
    """Dashboard recent meetings response envelope."""

    success: bool = True
    data: list[DashboardRecentMeeting]


class TimeSeriesPoint(BaseModel):
    """Time-series analytics point."""

    period: str
    total: int


class DashboardAnalyticsData(BaseModel):
    """Aggregated analytics for dashboard reporting."""

    meetings_per_day: list[TimeSeriesPoint]
    meetings_per_week: list[TimeSeriesPoint]
    meetings_per_month: list[TimeSeriesPoint]
    average_meeting_length: float | None
    most_common_file_type: str | None
    average_ai_processing_duration: float | None
    longest_meeting: DashboardRecentMeeting | None
    shortest_meeting: DashboardRecentMeeting | None
    largest_uploaded_file: DashboardRecentMeeting | None
    most_active_day: str | None


class DashboardAnalyticsResponse(APIResponse):
    """Dashboard analytics response envelope."""

    success: bool = True
    data: DashboardAnalyticsData


class DashboardPagination(BaseModel):
    """Pagination metadata."""

    current_page: int
    page_size: int
    total_records: int
    total_pages: int
    has_next: bool
    has_previous: bool


class DashboardMeetingListData(BaseModel):
    """Paginated dashboard meeting list."""

    pagination: DashboardPagination
    results: list[DashboardRecentMeeting]


class DashboardMeetingListResponse(APIResponse):
    """Dashboard meeting list response envelope."""

    success: bool = True
    data: DashboardMeetingListData


class DashboardSearchResponse(DashboardMeetingListResponse):
    """Dashboard search response envelope."""


class DashboardMeetingFilters(BaseModel):
    """Validated dashboard meeting filter values."""

    keyword: str | None = Field(default=None, max_length=255)
    processing_status: ProcessingStatus | None = None
    file_type: str | None = Field(default=None, max_length=20)
    date_from: date | None = None
    date_to: date | None = None
    min_duration: int | None = Field(default=None, ge=0)
    max_duration: int | None = Field(default=None, ge=0)
    has_transcript: bool | None = None
    has_summary: bool | None = None
    sort_by: str = "newest"
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
