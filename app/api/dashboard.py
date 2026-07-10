"""Dashboard and analytics API routes."""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user
from app.database.database import get_db
from app.models.enums import ProcessingStatus
from app.models.user import User
from app.schemas.dashboard import (
    DashboardAnalyticsResponse,
    DashboardMeetingFilters,
    DashboardMeetingListResponse,
    DashboardOverviewResponse,
    DashboardRecentResponse,
    DashboardSearchResponse,
)
from app.services.dashboard_service import DashboardService

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])


def get_dashboard_service(db: Annotated[Session, Depends(get_db)]) -> DashboardService:
    """Provide the dashboard service."""
    return DashboardService(db)


@router.get(
    "/overview",
    response_model=DashboardOverviewResponse,
    summary="Get dashboard overview",
    description="Return high-level dashboard metrics for the authenticated user.",
)
def get_dashboard_overview(
    current_user: Annotated[User, Depends(get_current_user)],
    dashboard_service: Annotated[DashboardService, Depends(get_dashboard_service)],
) -> DashboardOverviewResponse:
    """Return dashboard overview statistics."""
    data = dashboard_service.get_overview(current_user)
    return DashboardOverviewResponse(message="Dashboard overview retrieved successfully.", data=data)


@router.get(
    "/recent",
    response_model=DashboardRecentResponse,
    summary="Get recent meetings",
    description="Return the latest meetings for the authenticated user.",
)
def get_recent_meetings(
    current_user: Annotated[User, Depends(get_current_user)],
    dashboard_service: Annotated[DashboardService, Depends(get_dashboard_service)],
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> DashboardRecentResponse:
    """Return recent meetings."""
    data = dashboard_service.get_recent_meetings(current_user, limit)
    return DashboardRecentResponse(message="Recent meetings retrieved successfully.", data=data)


@router.get(
    "/analytics",
    response_model=DashboardAnalyticsResponse,
    summary="Get dashboard analytics",
    description="Return aggregated analytics for the authenticated user's meetings.",
)
def get_dashboard_analytics(
    current_user: Annotated[User, Depends(get_current_user)],
    dashboard_service: Annotated[DashboardService, Depends(get_dashboard_service)],
) -> DashboardAnalyticsResponse:
    """Return dashboard analytics."""
    data = dashboard_service.get_analytics(current_user)
    return DashboardAnalyticsResponse(message="Dashboard analytics retrieved successfully.", data=data)


@router.get(
    "/search",
    response_model=DashboardSearchResponse,
    summary="Search meetings",
    description="Search meetings by title, participants, transcript, summary, and keywords.",
)
def search_dashboard_meetings(
    current_user: Annotated[User, Depends(get_current_user)],
    dashboard_service: Annotated[DashboardService, Depends(get_dashboard_service)],
    keyword: Annotated[str, Query(min_length=1, max_length=255)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> DashboardSearchResponse:
    """Search meetings owned by the authenticated user."""
    data = dashboard_service.search_meetings(current_user, keyword, page, page_size)
    return DashboardSearchResponse(message="Dashboard search completed successfully.", data=data)


@router.get(
    "/meetings",
    response_model=DashboardMeetingListResponse,
    summary="List dashboard meetings",
    description="Return paginated meetings with filtering, searching, and sorting.",
)
def list_dashboard_meetings(
    current_user: Annotated[User, Depends(get_current_user)],
    dashboard_service: Annotated[DashboardService, Depends(get_dashboard_service)],
    keyword: Annotated[str | None, Query(max_length=255)] = None,
    processing_status: ProcessingStatus | None = None,
    file_type: Annotated[str | None, Query(max_length=20)] = None,
    date_from: date | None = None,
    date_to: date | None = None,
    min_duration: Annotated[int | None, Query(ge=0)] = None,
    max_duration: Annotated[int | None, Query(ge=0)] = None,
    has_transcript: bool | None = None,
    has_summary: bool | None = None,
    sort_by: Literal["newest", "oldest", "title", "duration", "processing_status", "upload_date"] = "newest",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> DashboardMeetingListResponse:
    """Return dashboard meeting list."""
    filters = DashboardMeetingFilters(
        keyword=keyword,
        processing_status=processing_status,
        file_type=file_type,
        date_from=date_from,
        date_to=date_to,
        min_duration=min_duration,
        max_duration=max_duration,
        has_transcript=has_transcript,
        has_summary=has_summary,
        sort_by=sort_by,
        page=page,
        page_size=page_size,
    )
    data = dashboard_service.list_meetings(current_user, filters)
    return DashboardMeetingListResponse(message="Dashboard meetings retrieved successfully.", data=data)
