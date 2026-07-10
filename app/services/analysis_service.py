"""Transcript analysis service for structured meeting intelligence."""

import json
import logging
from datetime import UTC, date, datetime, time
from typing import Any

import anyio
from fastapi import HTTPException, status
from openai import APIConnectionError, APIError, APITimeoutError, OpenAI, RateLimitError
from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.action_item import ActionItem
from app.models.enums import ProcessingStatus
from app.models.meeting import Meeting
from app.models.user import User
from app.prompts.meeting_analysis import MEETING_ANALYSIS_SYSTEM_PROMPT, build_meeting_analysis_prompt
from app.schemas.analysis import AnalysisResult, MeetingSummaryData, SummaryActionItem
from app.services.chunk_analysis_service import ChunkAnalysisService
from app.services.chunking_service import ChunkingService
from app.services.summary_merger_service import SummaryMergerService

logger = logging.getLogger(__name__)

TRANSIENT_ANALYSIS_ERRORS = (APITimeoutError, APIConnectionError, RateLimitError)


class AnalysisService:
    """Analyze transcribed meetings and persist structured intelligence."""

    def __init__(
        self,
        db: Session,
        chunking_service: ChunkingService | None = None,
        chunk_analysis_service: ChunkAnalysisService | None = None,
        summary_merger_service: SummaryMergerService | None = None,
    ) -> None:
        """Initialize the service with a database session and optional OpenAI client."""
        self.db = db
        self.client = (
            OpenAI(api_key=settings.OPENAI_API_KEY, timeout=settings.OPENAI_REQUEST_TIMEOUT_SECONDS)
            if settings.OPENAI_API_KEY
            else None
        )
        self.chunking_service = chunking_service or ChunkingService()
        self.chunk_analysis_service = chunk_analysis_service or ChunkAnalysisService()
        self.summary_merger_service = summary_merger_service or SummaryMergerService()

    async def analyze_meeting(self, user: User, meeting_id: int) -> MeetingSummaryData:
        """Analyze a transcribed meeting and store structured sections separately."""
        meeting = self._get_owned_meeting(user.id, meeting_id)
        self._validate_analysis_allowed(meeting)
        self._update_status(meeting, ProcessingStatus.ANALYZING)

        try:
            analysis_result = await self._analyze_with_strategy(meeting)
            self._store_analysis(meeting, analysis_result)
            meeting.processing_status = ProcessingStatus.COMPLETED
            meeting.processing_progress = 100
            self.db.commit()
            self.db.refresh(meeting)
        except HTTPException:
            self._mark_failed(meeting)
            raise
        except SQLAlchemyError as exc:
            self.db.rollback()
            logger.exception("Failed to persist analysis for meeting_id=%s", meeting_id)
            self._mark_failed(meeting)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to save meeting analysis.",
            ) from exc
        except Exception as exc:
            logger.exception("Unexpected analysis failure for meeting_id=%s", meeting_id)
            self._mark_failed(meeting)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Meeting analysis failed.",
            ) from exc

        return self._build_summary(meeting)

    async def _analyze_with_strategy(self, meeting: Meeting) -> AnalysisResult:
        """Use single-pass or chunked analysis depending on transcript size."""
        transcript = (meeting.transcript or "").strip()
        if not transcript:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Transcript not found.",
            )

        if not self.chunking_service.should_chunk(transcript):
            logger.info("Using single-pass transcript analysis for meeting_id=%s", meeting.id)
            self._update_progress(meeting, 85)
            return await self._analyze_transcript(transcript)

        logger.info("Using chunked transcript analysis for meeting_id=%s", meeting.id)
        self._update_progress(meeting, 65)
        chunks = self.chunking_service.create_chunks(transcript)
        partial_results: list[AnalysisResult] = []

        for chunk in chunks:
            chunk_progress = self._calculate_chunk_progress(chunk.index, chunk.total)
            self._update_progress(meeting, chunk_progress)
            partial_results.append(await self.chunk_analysis_service.analyze_chunk(chunk))

        self._update_progress(meeting, 95)
        return await self.summary_merger_service.merge(partial_results)

    def get_summary(self, user: User, meeting_id: int) -> MeetingSummaryData:
        """Return stored structured intelligence for an owned meeting."""
        meeting = self._get_owned_meeting(user.id, meeting_id)
        if meeting.processing_status != ProcessingStatus.COMPLETED or not meeting.executive_summary:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Meeting summary not found.",
            )

        return self._build_summary(meeting)

    async def _analyze_transcript(self, transcript: str) -> AnalysisResult:
        """Send a transcript to OpenAI and parse the structured JSON response."""
        if self.client is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="AI analysis is not configured.",
            )

        for attempt in range(1, settings.TRANSCRIPTION_MAX_RETRIES + 1):
            try:
                raw_response = await anyio.to_thread.run_sync(self._analyze_transcript_sync, transcript)
                return self._parse_analysis_response(raw_response)
            except TRANSIENT_ANALYSIS_ERRORS as exc:
                logger.warning("Transient OpenAI analysis failure on attempt %s", attempt)
                if attempt >= settings.TRANSCRIPTION_MAX_RETRIES:
                    raise self._safe_openai_error("AI analysis temporarily failed.") from exc
                await anyio.sleep(min(2**attempt, 10))
            except APIError as exc:
                logger.exception("OpenAI API failed during analysis")
                raise self._safe_openai_error("AI analysis failed.") from exc

        raise self._safe_openai_error("AI analysis failed.")

    def _analyze_transcript_sync(self, transcript: str) -> str:
        """Run the synchronous OpenAI analysis request."""
        if self.client is None:
            raise RuntimeError("OpenAI client is not configured.")

        response = self.client.chat.completions.create(
            model=settings.OPENAI_ANALYSIS_MODEL,
            messages=[
                {"role": "system", "content": MEETING_ANALYSIS_SYSTEM_PROMPT},
                {"role": "user", "content": build_meeting_analysis_prompt(transcript)},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        content = response.choices[0].message.content
        if not content:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="AI analysis returned no content.",
            )
        return content

    def _parse_analysis_response(self, response_text: str) -> AnalysisResult:
        """Parse and validate the structured JSON analysis response."""
        try:
            payload = json.loads(self._strip_json_response(response_text))
            return AnalysisResult.model_validate(payload)
        except (json.JSONDecodeError, ValidationError) as exc:
            logger.exception("OpenAI analysis response failed structured validation")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="AI analysis returned invalid structured data.",
            ) from exc

    def _store_analysis(self, meeting: Meeting, analysis_result: AnalysisResult) -> None:
        """Store analysis sections in their dedicated database fields."""
        meeting.executive_summary = analysis_result.executive_summary
        meeting.key_points = analysis_result.key_points
        meeting.participants = analysis_result.participants
        meeting.key_decisions = analysis_result.key_decisions
        meeting.deadlines = [deadline.model_dump() for deadline in analysis_result.deadlines]
        meeting.risks = analysis_result.risks
        meeting.next_steps = analysis_result.next_steps

        self.db.execute(delete(ActionItem).where(ActionItem.meeting_id == meeting.id))
        self.db.add_all(
            ActionItem(
                meeting_id=meeting.id,
                task=action_item.task,
                assignee=action_item.assignee,
                deadline=self._parse_optional_datetime(action_item.deadline),
            )
            for action_item in analysis_result.action_items
        )

    def _build_summary(self, meeting: Meeting) -> MeetingSummaryData:
        """Build a response object from stored meeting intelligence."""
        action_items = self.db.scalars(select(ActionItem).where(ActionItem.meeting_id == meeting.id)).all()
        return MeetingSummaryData(
            id=meeting.id,
            processing_status=meeting.processing_status,
            executive_summary=meeting.executive_summary,
            key_points=meeting.key_points,
            action_items=[
                SummaryActionItem(
                    id=action_item.id,
                    task=action_item.task,
                    assignee=action_item.assignee,
                    deadline=action_item.deadline,
                    completed=action_item.completed,
                )
                for action_item in action_items
            ],
            participants=meeting.participants,
            key_decisions=meeting.key_decisions,
            deadlines=meeting.deadlines,
            risks=meeting.risks,
            next_steps=meeting.next_steps,
        )

    def _get_owned_meeting(self, user_id: int, meeting_id: int) -> Meeting:
        """Return a meeting owned by the user or raise a not-found response."""
        meeting = self.db.scalar(select(Meeting).where(Meeting.id == meeting_id, Meeting.user_id == user_id))
        if meeting is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Meeting not found.",
            )
        return meeting

    def _validate_analysis_allowed(self, meeting: Meeting) -> None:
        """Validate that a meeting is ready for transcript analysis."""
        if meeting.processing_status == ProcessingStatus.ANALYZING:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Meeting is already being analyzed.",
            )

        if meeting.processing_status == ProcessingStatus.COMPLETED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Meeting has already been analyzed.",
            )

        if meeting.processing_status != ProcessingStatus.TRANSCRIBED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Meeting must be transcribed before analysis.",
            )

        if not meeting.transcript:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Transcript not found.",
            )

    def _update_status(self, meeting: Meeting, processing_status: ProcessingStatus) -> None:
        """Persist an analysis status transition."""
        meeting.processing_status = processing_status
        if processing_status == ProcessingStatus.ANALYZING:
            meeting.processing_progress = max(meeting.processing_progress, 65)
        self.db.commit()
        self.db.refresh(meeting)

    def _update_progress(self, meeting: Meeting, progress: int) -> None:
        """Persist a monotonic progress update."""
        meeting.processing_progress = max(meeting.processing_progress, min(progress, 99))
        self.db.commit()
        self.db.refresh(meeting)

    def _calculate_chunk_progress(self, chunk_index: int, chunk_count: int) -> int:
        """Calculate analysis progress for the current chunk."""
        if chunk_count <= 0:
            return 75
        progress_span = 25
        return 70 + round((chunk_index / chunk_count) * progress_span)

    def _mark_failed(self, meeting: Meeting) -> None:
        """Mark analysis as failed safely."""
        meeting.processing_status = ProcessingStatus.FAILED
        self.db.commit()

    def _safe_openai_error(self, message: str) -> HTTPException:
        """Return a safe client-facing error for AI provider failures."""
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=message,
        )

    def _strip_json_response(self, response_text: str) -> str:
        """Remove markdown fences if a provider returns them despite instructions."""
        stripped_response = response_text.strip()
        if stripped_response.startswith("```json"):
            return stripped_response.removeprefix("```json").removesuffix("```").strip()
        if stripped_response.startswith("```"):
            return stripped_response.removeprefix("```").removesuffix("```").strip()
        return stripped_response

    def _parse_optional_datetime(self, value: str | None) -> datetime | None:
        """Parse an optional ISO date or datetime from the analysis payload."""
        if not value:
            return None

        normalized_value = value.replace("Z", "+00:00")
        try:
            parsed_datetime = datetime.fromisoformat(normalized_value)
        except ValueError:
            try:
                parsed_date = date.fromisoformat(value)
            except ValueError:
                logger.warning("Ignoring non-ISO action item deadline")
                return None
            return datetime.combine(parsed_date, time.min, tzinfo=UTC)

        if parsed_datetime.tzinfo is None:
            return parsed_datetime.replace(tzinfo=UTC)
        return parsed_datetime
