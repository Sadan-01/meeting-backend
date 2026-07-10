"""Dashboard analytics service."""

import logging
import math
import time
from collections import Counter
from datetime import UTC, date, datetime, time as datetime_time, timedelta
from typing import Any

from sqlalchemy import String, and_, cast, desc, func, or_, select
from sqlalchemy.orm import Session, load_only

from app.models.enums import ProcessingStatus
from app.models.meeting import Meeting
from app.models.user import User
from app.schemas.dashboard import (
    DashboardAnalyticsData,
    DashboardMeetingFilters,
    DashboardMeetingListData,
    DashboardOverviewData,
    DashboardPagination,
    DashboardRecentMeeting,
    TimeSeriesPoint,
)

logger = logging.getLogger(__name__)

ACTIVE_PROCESSING_STATUSES = {
    ProcessingStatus.QUEUED,
    ProcessingStatus.PROCESSING,
    ProcessingStatus.TRANSCRIBED,
    ProcessingStatus.ANALYZING,
}


class DashboardService:
    """Service for user-scoped dashboard statistics and meeting discovery."""

    def __init__(self, db: Session) -> None:
        """Initialize the dashboard service with a database session."""
        self.db = db

    def get_overview(self, user: User) -> DashboardOverviewData:
        """Return dashboard overview statistics for a user."""
        started_at = time.perf_counter()
        logger.info("Dashboard overview requested for user_id=%s", user.id)

        today_start = self._start_of_day(self._now())
        week_start = today_start - timedelta(days=today_start.weekday())
        month_start = today_start.replace(day=1)

        data = DashboardOverviewData(
            total_meetings=self._count(user.id),
            completed_meetings=self._count(user.id, Meeting.processing_status == ProcessingStatus.COMPLETED),
            processing_meetings=self._count(user.id, Meeting.processing_status.in_(ACTIVE_PROCESSING_STATUSES)),
            queued_meetings=self._count(user.id, Meeting.processing_status == ProcessingStatus.QUEUED),
            failed_meetings=self._count(user.id, Meeting.processing_status == ProcessingStatus.FAILED),
            meetings_uploaded_today=self._count(user.id, Meeting.created_at >= today_start),
            meetings_uploaded_this_week=self._count(user.id, Meeting.created_at >= week_start),
            meetings_uploaded_this_month=self._count(user.id, Meeting.created_at >= month_start),
            average_meeting_duration=self._scalar_float(
                select(func.avg(Meeting.duration_seconds)).where(Meeting.user_id == user.id)
            ),
            average_processing_time=None,
            total_transcript_size=self._total_transcript_size(user.id),
            total_storage_used=self.db.scalar(select(func.coalesce(func.sum(Meeting.file_size), 0)).where(Meeting.user_id == user.id)) or 0,
            recent_meetings=self._recent_meetings(user.id, limit=5),
            processing_progress=self._processing_progress(user.id),
        )
        logger.info("Dashboard overview generated user_id=%s duration_ms=%s", user.id, self._elapsed_ms(started_at))
        return data

    def get_recent_meetings(self, user: User, limit: int = 10) -> list[DashboardRecentMeeting]:
        """Return recent meetings for a user."""
        logger.info("Dashboard recent meetings requested for user_id=%s", user.id)
        return self._recent_meetings(user.id, limit=limit)

    def get_analytics(self, user: User) -> DashboardAnalyticsData:
        """Return aggregated meeting analytics for a user."""
        started_at = time.perf_counter()
        logger.info("Dashboard analytics requested for user_id=%s", user.id)
        meeting_rows = self.db.execute(
            self._compact_select()
            .options(self._compact_load_options())
            .where(Meeting.user_id == user.id)
        ).all()
        meetings = [row[0] for row in meeting_rows]
        has_transcript_by_id = {row[0].id: bool(row[1]) for row in meeting_rows}
        has_summary_by_id = {row[0].id: bool(row[2]) for row in meeting_rows}
        analytics = DashboardAnalyticsData(
            meetings_per_day=self._group_by_period(meetings, "day"),
            meetings_per_week=self._group_by_period(meetings, "week"),
            meetings_per_month=self._group_by_period(meetings, "month"),
            average_meeting_length=self._average_duration(meetings),
            most_common_file_type=self._most_common_file_type(meetings),
            average_ai_processing_duration=None,
            longest_meeting=self._meeting_with_duration(meetings, has_transcript_by_id, has_summary_by_id, longest=True),
            shortest_meeting=self._meeting_with_duration(meetings, has_transcript_by_id, has_summary_by_id, longest=False),
            largest_uploaded_file=self._largest_file(meetings, has_transcript_by_id, has_summary_by_id),
            most_active_day=self._most_active_day(meetings),
        )
        logger.info("Dashboard analytics generated user_id=%s duration_ms=%s", user.id, self._elapsed_ms(started_at))
        return analytics

    def search_meetings(self, user: User, keyword: str, page: int, page_size: int) -> DashboardMeetingListData:
        """Search meetings by keyword."""
        logger.info("Dashboard search requested user_id=%s keyword_present=%s", user.id, bool(keyword))
        filters = DashboardMeetingFilters(keyword=keyword, page=page, page_size=page_size)
        return self.list_meetings(user, filters)

    def list_meetings(self, user: User, filters: DashboardMeetingFilters) -> DashboardMeetingListData:
        """Return paginated, filtered, sorted meetings."""
        started_at = time.perf_counter()
        query = self._compact_select().where(Meeting.user_id == user.id)
        query = self._apply_filters(query, filters)
        total_records = self.db.scalar(select(func.count()).select_from(query.subquery())) or 0
        query = self._apply_sort(query, filters.sort_by)
        rows = self.db.execute(query.offset((filters.page - 1) * filters.page_size).limit(filters.page_size)).all()

        total_pages = math.ceil(total_records / filters.page_size) if total_records else 0
        data = DashboardMeetingListData(
            pagination=DashboardPagination(
                current_page=filters.page,
                page_size=filters.page_size,
                total_records=total_records,
                total_pages=total_pages,
                has_next=filters.page < total_pages,
                has_previous=filters.page > 1 and total_pages > 0,
            ),
            results=[self._to_recent_meeting(row[0], has_transcript=bool(row[1]), has_summary=bool(row[2])) for row in rows],
        )
        logger.info("Dashboard meeting list generated user_id=%s duration_ms=%s", user.id, self._elapsed_ms(started_at))
        return data

    def _apply_filters(self, query: Any, filters: DashboardMeetingFilters) -> Any:
        """Apply safe filters to a meeting query."""
        if filters.keyword:
            keyword = f"%{filters.keyword.lower()}%"
            query = query.where(
                or_(
                    func.lower(Meeting.title).like(keyword),
                    func.lower(Meeting.transcript).like(keyword),
                    func.lower(Meeting.executive_summary).like(keyword),
                    func.lower(cast(Meeting.participants, String)).like(keyword),
                    func.lower(cast(Meeting.key_points, String)).like(keyword),
                    func.lower(cast(Meeting.key_decisions, String)).like(keyword),
                )
            )
        if filters.processing_status:
            query = query.where(Meeting.processing_status == filters.processing_status)
        if filters.file_type:
            file_type = filters.file_type.lower()
            if not file_type.startswith("."):
                file_type = f".{file_type}"
            query = query.where(func.lower(Meeting.file_extension) == file_type)
        if filters.date_from:
            query = query.where(Meeting.created_at >= self._date_start(filters.date_from))
        if filters.date_to:
            query = query.where(Meeting.created_at <= self._date_end(filters.date_to))
        if filters.min_duration is not None:
            query = query.where(Meeting.duration_seconds >= filters.min_duration)
        if filters.max_duration is not None:
            query = query.where(Meeting.duration_seconds <= filters.max_duration)
        if filters.has_transcript is not None:
            query = query.where(Meeting.transcript.is_not(None) if filters.has_transcript else Meeting.transcript.is_(None))
        if filters.has_summary is not None:
            query = query.where(
                Meeting.executive_summary.is_not(None) if filters.has_summary else Meeting.executive_summary.is_(None)
            )
        return query

    def _apply_sort(self, query: Any, sort_by: str) -> Any:
        """Apply a whitelisted sort option."""
        sort_map = {
            "newest": Meeting.created_at.desc(),
            "oldest": Meeting.created_at.asc(),
            "title": Meeting.title.asc(),
            "duration": Meeting.duration_seconds.desc().nullslast(),
            "processing_status": Meeting.processing_status.asc(),
            "upload_date": Meeting.created_at.desc(),
        }
        return query.order_by(sort_map.get(sort_by, Meeting.created_at.desc()))

    def _recent_meetings(self, user_id: int, limit: int) -> list[DashboardRecentMeeting]:
        """Return latest compact meeting rows."""
        rows = self.db.execute(
            self._compact_select()
            .where(Meeting.user_id == user_id)
            .order_by(desc(Meeting.created_at))
            .limit(limit)
        ).all()
        return [self._to_recent_meeting(row[0], has_transcript=bool(row[1]), has_summary=bool(row[2])) for row in rows]

    def _processing_progress(self, user_id: int) -> list[DashboardRecentMeeting]:
        """Return active meetings and progress."""
        rows = self.db.execute(
            self._compact_select()
            .where(and_(Meeting.user_id == user_id, Meeting.processing_status.in_(ACTIVE_PROCESSING_STATUSES)))
            .order_by(desc(Meeting.updated_at))
            .limit(10)
        ).all()
        return [self._to_recent_meeting(row[0], has_transcript=bool(row[1]), has_summary=bool(row[2])) for row in rows]

    def _compact_select(self) -> Any:
        """Return a compact meeting select that avoids loading large transcript text."""
        return select(
            Meeting,
            Meeting.transcript.is_not(None).label("has_transcript"),
            Meeting.executive_summary.is_not(None).label("has_summary"),
        ).options(self._compact_load_options())

    def _compact_load_options(self) -> Any:
        """Return compact Meeting columns needed for dashboard cards."""
        return load_only(
            Meeting.id,
            Meeting.title,
            Meeting.created_at,
            Meeting.processing_status,
            Meeting.duration_seconds,
            Meeting.file_extension,
            Meeting.file_size,
            Meeting.processing_progress,
        )

    def _to_recent_meeting(
        self,
        meeting: Meeting,
        *,
        has_transcript: bool | None = None,
        has_summary: bool | None = None,
    ) -> DashboardRecentMeeting:
        """Convert a meeting model into dashboard compact shape."""
        return DashboardRecentMeeting(
            id=meeting.id,
            title=meeting.title,
            upload_date=meeting.created_at,
            processing_status=meeting.processing_status,
            duration_seconds=meeting.duration_seconds,
            file_type=meeting.file_extension,
            has_transcript=bool(has_transcript),
            has_summary=bool(has_summary),
            processing_progress=meeting.processing_progress,
        )

    def _count(self, user_id: int, *conditions: Any) -> int:
        """Count user meetings with optional conditions."""
        return self.db.scalar(select(func.count()).select_from(Meeting).where(Meeting.user_id == user_id, *conditions)) or 0

    def _scalar_float(self, query: Any) -> float | None:
        """Return a scalar float from an aggregate query."""
        value = self.db.scalar(query)
        return float(value) if value is not None else None

    def _total_transcript_size(self, user_id: int) -> int:
        """Return total transcript character count."""
        value = self.db.scalar(
            select(func.coalesce(func.sum(func.length(Meeting.transcript)), 0)).where(Meeting.user_id == user_id)
        )
        return int(value or 0)

    def _group_by_period(self, meetings: list[Meeting], period: str) -> list[TimeSeriesPoint]:
        """Group meetings by date period in Python for database portability."""
        counter: Counter[str] = Counter()
        for meeting in meetings:
            created_at = meeting.created_at
            if period == "day":
                key = created_at.date().isoformat()
            elif period == "week":
                week_start = created_at.date() - timedelta(days=created_at.weekday())
                key = week_start.isoformat()
            else:
                key = f"{created_at.year:04d}-{created_at.month:02d}"
            counter[key] += 1
        return [TimeSeriesPoint(period=key, total=counter[key]) for key in sorted(counter)]

    def _average_duration(self, meetings: list[Meeting]) -> float | None:
        """Calculate average duration from meetings with duration."""
        durations = [meeting.duration_seconds for meeting in meetings if meeting.duration_seconds is not None]
        return sum(durations) / len(durations) if durations else None

    def _most_common_file_type(self, meetings: list[Meeting]) -> str | None:
        """Return the most common uploaded file type."""
        counter = Counter(meeting.file_extension for meeting in meetings if meeting.file_extension)
        return counter.most_common(1)[0][0] if counter else None

    def _meeting_with_duration(
        self,
        meetings: list[Meeting],
        has_transcript_by_id: dict[int, bool],
        has_summary_by_id: dict[int, bool],
        *,
        longest: bool,
    ) -> DashboardRecentMeeting | None:
        """Return longest or shortest meeting by duration."""
        candidates = [meeting for meeting in meetings if meeting.duration_seconds is not None]
        if not candidates:
            return None
        meeting = max(candidates, key=lambda item: item.duration_seconds or 0) if longest else min(candidates, key=lambda item: item.duration_seconds or 0)
        return self._to_recent_meeting(
            meeting,
            has_transcript=has_transcript_by_id.get(meeting.id, False),
            has_summary=has_summary_by_id.get(meeting.id, False),
        )

    def _largest_file(
        self,
        meetings: list[Meeting],
        has_transcript_by_id: dict[int, bool],
        has_summary_by_id: dict[int, bool],
    ) -> DashboardRecentMeeting | None:
        """Return largest uploaded file meeting."""
        if not meetings:
            return None
        meeting = max(meetings, key=lambda item: item.file_size)
        return self._to_recent_meeting(
            meeting,
            has_transcript=has_transcript_by_id.get(meeting.id, False),
            has_summary=has_summary_by_id.get(meeting.id, False),
        )

    def _most_active_day(self, meetings: list[Meeting]) -> str | None:
        """Return date with most uploads."""
        if not meetings:
            return None
        counter = Counter(meeting.created_at.date().isoformat() for meeting in meetings)
        return counter.most_common(1)[0][0]

    def _now(self) -> datetime:
        """Return current UTC datetime."""
        return datetime.now(UTC)

    def _start_of_day(self, value: datetime) -> datetime:
        """Return start of day for a datetime."""
        return datetime.combine(value.date(), datetime_time.min, tzinfo=UTC)

    def _date_start(self, value: date) -> datetime:
        """Return start datetime for a date."""
        return datetime.combine(value, datetime_time.min, tzinfo=UTC)

    def _date_end(self, value: date) -> datetime:
        """Return end datetime for a date."""
        return datetime.combine(value, datetime_time.max, tzinfo=UTC)

    def _elapsed_ms(self, started_at: float) -> int:
        """Return elapsed milliseconds."""
        return round((time.perf_counter() - started_at) * 1000)
