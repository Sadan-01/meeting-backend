"""Meeting upload and file-management business logic."""

import logging
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import ColumnElement, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

try:
    import aiofiles
except ImportError:  # pragma: no cover - production dependency is declared in requirements.txt
    aiofiles = None

from app.core.config import settings
from app.models.enums import ProcessingStatus
from app.models.meeting import Meeting
from app.models.user import User
from app.schemas.meeting import (
    MeetingListData,
    MeetingProcessData,
    MeetingProcessingStartData,
    MeetingPublic,
    MeetingStatusData,
    MeetingTranscriptData,
)
from app.services.audio_service import AudioService
from app.services.openai_service import OpenAIService
from app.utils.upload import (
    CHUNK_SIZE_BYTES,
    create_upload_directory,
    delete_meeting_directory,
    generate_safe_filename,
    get_meeting_file_path,
    sanitize_uploaded_filename,
    validate_file,
)

logger = logging.getLogger(__name__)


class MeetingService:
    """Service for authenticated meeting upload and management workflows."""

    def __init__(
        self,
        db: Session,
        audio_service: AudioService | None = None,
        openai_service: OpenAIService | None = None,
    ) -> None:
        """Initialize the service with a database session."""
        self.db = db
        self.audio_service = audio_service or AudioService()
        self.openai_service = openai_service or OpenAIService()

    async def upload_meeting(self, user: User, title: str, file: UploadFile) -> MeetingPublic:
        """Validate, store, and create a database record for a meeting upload."""
        normalized_title = title.strip()
        if not normalized_title:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Meeting title cannot be empty.",
            )

        file_extension = validate_file(file)
        original_filename = sanitize_uploaded_filename(file.filename)
        meeting_uuid, stored_filename = generate_safe_filename(file_extension)
        upload_directory = create_upload_directory(user.id, meeting_uuid)
        destination = upload_directory / stored_filename

        try:
            file_size = await self._save_upload_file(file, destination)
            meeting = Meeting(
                user_id=user.id,
                title=normalized_title,
                original_filename=original_filename,
                stored_filename=stored_filename,
                file_extension=file_extension,
                file_size=file_size,
                duration_seconds=None,
                processing_status=ProcessingStatus.UPLOADED,
                processing_progress=0,
            )
            self.db.add(meeting)
            self.db.commit()
            self.db.refresh(meeting)
        except HTTPException:
            self.db.rollback()
            self._safe_delete_directory(user.id, stored_filename)
            raise
        except SQLAlchemyError as exc:
            self.db.rollback()
            self._safe_delete_directory(user.id, stored_filename)
            logger.exception("Failed to create meeting record for user_id=%s", user.id)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to save meeting metadata.",
            ) from exc
        except Exception as exc:
            self.db.rollback()
            self._safe_delete_directory(user.id, stored_filename)
            logger.exception("Failed to upload meeting for user_id=%s", user.id)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to upload meeting.",
            ) from exc

        return MeetingPublic.model_validate(meeting)

    def list_meetings(
        self,
        user: User,
        page: int,
        page_size: int,
        sort_by: str,
        sort_order: str,
    ) -> MeetingListData:
        """Return paginated meetings owned by the authenticated user."""
        order_column = self._get_sort_column(sort_by)
        order_expression = order_column.asc() if sort_order == "asc" else order_column.desc()

        base_query = select(Meeting).where(Meeting.user_id == user.id)
        total = self.db.scalar(select(func.count()).select_from(base_query.subquery())) or 0
        meetings = self.db.scalars(
            base_query.order_by(order_expression).offset((page - 1) * page_size).limit(page_size)
        ).all()

        return MeetingListData(
            items=[MeetingPublic.model_validate(meeting) for meeting in meetings],
            page=page,
            page_size=page_size,
            total=total,
        )

    def get_meeting(self, user: User, meeting_id: int) -> MeetingPublic:
        """Return a meeting if it belongs to the authenticated user."""
        meeting = self._get_owned_meeting(user.id, meeting_id)
        return MeetingPublic.model_validate(meeting)

    def delete_meeting(self, user: User, meeting_id: int) -> None:
        """Delete an owned meeting record and its uploaded files."""
        meeting = self._get_owned_meeting(user.id, meeting_id)
        stored_filename = meeting.stored_filename

        try:
            delete_meeting_directory(user.id, stored_filename)
            self.db.delete(meeting)
            self.db.commit()
        except HTTPException:
            self.db.rollback()
            raise
        except Exception as exc:
            self.db.rollback()
            logger.exception("Failed to delete meeting_id=%s for user_id=%s", meeting_id, user.id)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to delete meeting.",
            ) from exc

    async def process_meeting(self, user: User, meeting_id: int) -> MeetingProcessData:
        """Transcribe an uploaded meeting owned by the authenticated user."""
        meeting = self._get_owned_meeting(user.id, meeting_id)
        self._validate_processing_allowed(meeting)
        self._update_processing_status(meeting, ProcessingStatus.PROCESSING)

        try:
            media_path = get_meeting_file_path(user.id, meeting.stored_filename)
            prepared_audio = self.audio_service.prepare_for_transcription(media_path, meeting.file_extension)
            transcript = await self.openai_service.transcribe_audio(prepared_audio.file_path)

            meeting.duration_seconds = prepared_audio.duration_seconds
            meeting.transcript = transcript
            meeting.processing_status = ProcessingStatus.TRANSCRIBED
            meeting.processing_progress = max(meeting.processing_progress, 60)
            self.db.commit()
            self.db.refresh(meeting)
        except HTTPException:
            self._mark_processing_failed(meeting)
            raise
        except Exception as exc:
            self._mark_processing_failed(meeting)
            logger.exception("Unexpected meeting processing failure for meeting_id=%s", meeting_id)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Meeting processing failed.",
            ) from exc

        return MeetingProcessData(
            id=meeting.id,
            processing_status=meeting.processing_status,
            duration_seconds=meeting.duration_seconds,
            transcript_available=bool(meeting.transcript),
        )

    def get_transcript(self, user: User, meeting_id: int) -> MeetingTranscriptData:
        """Return the transcript for an owned meeting."""
        meeting = self._get_owned_meeting(user.id, meeting_id)
        if not meeting.transcript:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Transcript not found.",
            )

        return MeetingTranscriptData(
            id=meeting.id,
            transcript=meeting.transcript,
            processing_status=meeting.processing_status,
        )

    def queue_meeting_processing(self, user: User, meeting_id: int) -> MeetingProcessingStartData:
        """Queue a meeting for non-blocking background processing."""
        meeting = self._get_owned_meeting(user.id, meeting_id)
        self._validate_queue_allowed(meeting)

        meeting.processing_status = ProcessingStatus.QUEUED
        meeting.processing_progress = 5
        self.db.commit()
        self.db.refresh(meeting)

        return MeetingProcessingStartData(
            id=meeting.id,
            processing_status=meeting.processing_status,
            processing_progress=meeting.processing_progress,
        )

    def get_processing_status(self, user: User, meeting_id: int) -> MeetingStatusData:
        """Return current processing status and progress for an owned meeting."""
        meeting = self._get_owned_meeting(user.id, meeting_id)
        return MeetingStatusData(
            id=meeting.id,
            processing_status=meeting.processing_status,
            processing_progress=meeting.processing_progress,
            updated_at=meeting.updated_at,
        )

    async def _save_upload_file(self, file: UploadFile, destination: Path) -> int:
        """Persist an uploaded file in chunks and return the saved byte count."""
        file_size = 0

        try:
            if aiofiles is not None:
                output_file = await aiofiles.open(destination, "wb")
                try:
                    while chunk := await file.read(CHUNK_SIZE_BYTES):
                        file_size = self._validate_chunk_size(file_size, len(chunk))
                        await output_file.write(chunk)
                    await output_file.flush()
                finally:
                    await output_file.close()
            else:
                with destination.open("wb") as output_file:
                    while chunk := await file.read(CHUNK_SIZE_BYTES):
                        file_size = self._validate_chunk_size(file_size, len(chunk))
                        output_file.write(chunk)
        finally:
            await file.close()

        if file_size == 0:
            destination.unlink(missing_ok=True)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded file cannot be empty.",
            )

        return file_size

    def _validate_chunk_size(self, current_size: int, chunk_size: int) -> int:
        """Return the new file size or reject files larger than configured maximum."""
        next_size = current_size + chunk_size
        if next_size > settings.MAX_UPLOAD_SIZE:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="Uploaded file exceeds the maximum allowed size.",
            )
        return next_size

    def _get_owned_meeting(self, user_id: int, meeting_id: int) -> Meeting:
        """Return a meeting owned by a user or raise a not-found response."""
        meeting = self.db.scalar(select(Meeting).where(Meeting.id == meeting_id, Meeting.user_id == user_id))
        if meeting is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Meeting not found.",
            )
        return meeting

    def _validate_processing_allowed(self, meeting: Meeting) -> None:
        """Reject meetings that cannot be processed."""
        if meeting.processing_status == ProcessingStatus.PROCESSING:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Meeting is already being processed.",
            )

        if meeting.processing_status == ProcessingStatus.ANALYZING:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Meeting is already being analyzed.",
            )

        if meeting.processing_status in {ProcessingStatus.TRANSCRIBED, ProcessingStatus.COMPLETED}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Meeting has already been processed.",
            )

    def _validate_queue_allowed(self, meeting: Meeting) -> None:
        """Reject meetings that cannot be queued for background processing."""
        if meeting.processing_status in {
            ProcessingStatus.QUEUED,
            ProcessingStatus.PROCESSING,
            ProcessingStatus.ANALYZING,
        }:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Meeting processing is already in progress.",
            )

        if meeting.processing_status == ProcessingStatus.COMPLETED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Meeting processing is already completed.",
            )

    def _update_processing_status(self, meeting: Meeting, processing_status: ProcessingStatus) -> None:
        """Persist a meeting processing status update."""
        meeting.processing_status = processing_status
        if processing_status == ProcessingStatus.PROCESSING:
            meeting.processing_progress = max(meeting.processing_progress, 20)
        elif processing_status == ProcessingStatus.TRANSCRIBED:
            meeting.processing_progress = max(meeting.processing_progress, 60)
        self.db.commit()
        self.db.refresh(meeting)

    def _mark_processing_failed(self, meeting: Meeting) -> None:
        """Mark meeting processing as failed without exposing the underlying error."""
        meeting.processing_status = ProcessingStatus.FAILED
        self.db.commit()

    def _get_sort_column(self, sort_by: str) -> ColumnElement[object]:
        """Return an allowed SQLAlchemy sort column."""
        allowed_sort_columns = {
            "created_at": Meeting.created_at,
            "title": Meeting.title,
            "file_size": Meeting.file_size,
            "processing_status": Meeting.processing_status,
        }
        return allowed_sort_columns.get(sort_by, Meeting.created_at)

    def _safe_delete_directory(self, user_id: int, stored_filename: str) -> None:
        """Best-effort cleanup for a meeting upload directory."""
        try:
            delete_meeting_directory(user_id, stored_filename)
        except Exception:
            logger.exception("Failed to clean up upload directory for user_id=%s", user_id)
