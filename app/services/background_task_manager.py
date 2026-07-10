"""Background task orchestration for meeting AI processing."""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.database import SessionLocal
from app.models.enums import ProcessingStatus
from app.models.meeting import Meeting
from app.models.user import User
from app.services.analysis_service import AnalysisService
from app.services.meeting_service import MeetingService

logger = logging.getLogger(__name__)


async def run_meeting_processing_pipeline(user_id: int, meeting_id: int) -> None:
    """Run transcription and analysis for a queued meeting in the background."""
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        if user is None:
            logger.warning("Background processing skipped because user_id=%s no longer exists", user_id)
            return

        meeting = _get_meeting(db, user_id, meeting_id)
        if meeting is None:
            logger.warning("Background processing skipped because meeting_id=%s no longer exists", meeting_id)
            return

        logger.info("Background processing started for meeting_id=%s user_id=%s", meeting_id, user_id)
        _ensure_queued(meeting, db)

        if not meeting.transcript:
            await MeetingService(db).process_meeting(user, meeting_id)
            meeting = _get_meeting(db, user_id, meeting_id)

        if meeting is None:
            return

        if meeting.processing_status == ProcessingStatus.QUEUED and meeting.transcript:
            meeting.processing_status = ProcessingStatus.TRANSCRIBED
            meeting.processing_progress = max(meeting.processing_progress, 60)
            db.commit()
            db.refresh(meeting)

        if meeting.processing_status == ProcessingStatus.TRANSCRIBED:
            await AnalysisService(db).analyze_meeting(user, meeting_id)

        _set_completed_progress(db, meeting_id)
        logger.info("Background processing completed for meeting_id=%s user_id=%s", meeting_id, user_id)
    except Exception:
        logger.exception("Background processing failed for meeting_id=%s user_id=%s", meeting_id, user_id)
        _mark_failed(db, meeting_id)
    finally:
        db.close()


def _get_meeting(db: Session, user_id: int, meeting_id: int) -> Meeting | None:
    """Return a meeting by owner and ID."""
    return db.scalar(select(Meeting).where(Meeting.id == meeting_id, Meeting.user_id == user_id))


def _ensure_queued(meeting: Meeting, db: Session) -> None:
    """Ensure the task starts from a queued state."""
    if meeting.processing_status != ProcessingStatus.QUEUED:
        meeting.processing_status = ProcessingStatus.QUEUED
        meeting.processing_progress = max(meeting.processing_progress, 5)
        db.commit()
        db.refresh(meeting)


def _set_completed_progress(db: Session, meeting_id: int) -> None:
    """Ensure completed meetings report 100 percent progress."""
    meeting = db.get(Meeting, meeting_id)
    if meeting and meeting.processing_status == ProcessingStatus.COMPLETED:
        meeting.processing_progress = 100
        db.commit()


def _mark_failed(db: Session, meeting_id: int) -> None:
    """Best-effort failure status update for background task errors."""
    db.rollback()
    meeting = db.get(Meeting, meeting_id)
    if meeting is None:
        return

    meeting.processing_status = ProcessingStatus.FAILED
    db.commit()
