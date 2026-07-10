"""Meeting upload and file-management API routes."""

from typing import Annotated, Literal
from io import BytesIO

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user
from app.database.database import get_db
from app.models.user import User
from app.schemas.analysis import MeetingAnalysisResponse, MeetingSummaryResponse
from app.schemas.auth import MessageResponse
from app.schemas.chat import ChatAnswerResponse, ChatHistoryListResponse, ChatRequest
from app.schemas.meeting import (
    MeetingDetailResponse,
    MeetingListResponse,
    MeetingProcessResponse,
    MeetingProcessingStartResponse,
    MeetingStatusResponse,
    MeetingTranscriptResponse,
    MeetingUploadRequest,
    MeetingUploadResponse,
)
from app.services.analysis_service import AnalysisService
from app.services.background_task_manager import run_meeting_processing_pipeline
from app.services.chat_service import ChatService
from app.services.export_service import ExportFile, ExportService
from app.services.meeting_service import MeetingService

router = APIRouter(prefix="/api/meetings", tags=["Meetings"])


def get_meeting_service(db: Annotated[Session, Depends(get_db)]) -> MeetingService:
    """Provide the meeting service."""
    return MeetingService(db)


def get_analysis_service(db: Annotated[Session, Depends(get_db)]) -> AnalysisService:
    """Provide the analysis service."""
    return AnalysisService(db)


def get_chat_service(db: Annotated[Session, Depends(get_db)]) -> ChatService:
    """Provide the meeting chat service."""
    return ChatService(db)


def get_export_service(db: Annotated[Session, Depends(get_db)]) -> ExportService:
    """Provide the meeting export service."""
    return ExportService(db)


def build_export_response(export_file: ExportFile) -> StreamingResponse:
    """Build a downloadable streaming response for an export file."""
    return StreamingResponse(
        BytesIO(export_file.content),
        media_type=export_file.media_type,
        headers={"Content-Disposition": f'attachment; filename="{export_file.filename}"'},
    )


@router.post(
    "/upload",
    response_model=MeetingUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload meeting recording",
    description="Upload a supported meeting recording and create a meeting record for future AI processing.",
)
async def upload_meeting(
    current_user: Annotated[User, Depends(get_current_user)],
    meeting_service: Annotated[MeetingService, Depends(get_meeting_service)],
    title: Annotated[str, Form(..., min_length=1, max_length=255)],
    file: Annotated[UploadFile, File(...)],
) -> MeetingUploadResponse:
    """Upload a meeting recording for the authenticated user."""
    upload_payload = MeetingUploadRequest(title=title)
    meeting = await meeting_service.upload_meeting(current_user, upload_payload.title, file)
    return MeetingUploadResponse(message="Meeting uploaded successfully.", data=meeting)


@router.get(
    "",
    response_model=MeetingListResponse,
    summary="List current user's meetings",
    description="Return paginated meetings owned by the authenticated user, newest first by default.",
)
def list_meetings(
    current_user: Annotated[User, Depends(get_current_user)],
    meeting_service: Annotated[MeetingService, Depends(get_meeting_service)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    sort_by: Annotated[
        Literal["created_at", "title", "file_size", "processing_status"],
        Query(),
    ] = "created_at",
    sort_order: Annotated[Literal["asc", "desc"], Query()] = "desc",
) -> MeetingListResponse:
    """Return meetings belonging to the authenticated user."""
    meetings = meeting_service.list_meetings(current_user, page, page_size, sort_by, sort_order)
    return MeetingListResponse(message="Meetings retrieved successfully.", data=meetings)


@router.post(
    "/{meeting_id}/process",
    response_model=MeetingProcessResponse,
    summary="Process meeting transcription",
    description="Transcribe an uploaded meeting recording owned by the authenticated user.",
)
async def process_meeting(
    meeting_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    meeting_service: Annotated[MeetingService, Depends(get_meeting_service)],
) -> MeetingProcessResponse:
    """Process a meeting recording into a transcript."""
    processing_data = await meeting_service.process_meeting(current_user, meeting_id)
    return MeetingProcessResponse(message="Meeting transcribed successfully.", data=processing_data)


@router.get(
    "/{meeting_id}/transcript",
    response_model=MeetingTranscriptResponse,
    summary="Get meeting transcript",
    description="Return the transcript for a processed meeting owned by the authenticated user.",
)
def get_meeting_transcript(
    meeting_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    meeting_service: Annotated[MeetingService, Depends(get_meeting_service)],
) -> MeetingTranscriptResponse:
    """Return the transcript for an owned meeting."""
    transcript_data = meeting_service.get_transcript(current_user, meeting_id)
    return MeetingTranscriptResponse(message="Transcript retrieved successfully.", data=transcript_data)


@router.post(
    "/{meeting_id}/start-processing",
    response_model=MeetingProcessingStartResponse,
    summary="Start background meeting processing",
    description="Queue a meeting for background transcription and analysis without blocking the HTTP request.",
)
def start_meeting_processing(
    meeting_id: int,
    background_tasks: BackgroundTasks,
    current_user: Annotated[User, Depends(get_current_user)],
    meeting_service: Annotated[MeetingService, Depends(get_meeting_service)],
) -> MeetingProcessingStartResponse:
    """Queue an owned meeting for asynchronous processing."""
    processing_data = meeting_service.queue_meeting_processing(current_user, meeting_id)
    background_tasks.add_task(run_meeting_processing_pipeline, current_user.id, meeting_id)
    return MeetingProcessingStartResponse(message="Processing started.", data=processing_data)


@router.get(
    "/{meeting_id}/status",
    response_model=MeetingStatusResponse,
    summary="Get meeting processing status",
    description="Return current processing status, progress percentage, and updated timestamp.",
)
def get_meeting_processing_status(
    meeting_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    meeting_service: Annotated[MeetingService, Depends(get_meeting_service)],
) -> MeetingStatusResponse:
    """Return status information for an owned meeting."""
    status_data = meeting_service.get_processing_status(current_user, meeting_id)
    return MeetingStatusResponse(message="Meeting status retrieved successfully.", data=status_data)


@router.post(
    "/{meeting_id}/analyze",
    response_model=MeetingAnalysisResponse,
    summary="Analyze meeting transcript",
    description="Analyze a completed transcript and store structured meeting intelligence.",
)
async def analyze_meeting(
    meeting_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    analysis_service: Annotated[AnalysisService, Depends(get_analysis_service)],
) -> MeetingAnalysisResponse:
    """Analyze an owned meeting transcript."""
    summary = await analysis_service.analyze_meeting(current_user, meeting_id)
    return MeetingAnalysisResponse(message="Meeting analysis completed successfully.", data=summary)


@router.get(
    "/{meeting_id}/summary",
    response_model=MeetingSummaryResponse,
    summary="Get meeting summary",
    description="Return stored structured meeting intelligence for an analyzed meeting.",
)
def get_meeting_summary(
    meeting_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    analysis_service: Annotated[AnalysisService, Depends(get_analysis_service)],
) -> MeetingSummaryResponse:
    """Return stored structured intelligence for an owned meeting."""
    summary = analysis_service.get_summary(current_user, meeting_id)
    return MeetingSummaryResponse(message="Meeting summary retrieved successfully.", data=summary)


@router.post(
    "/{meeting_id}/chat",
    response_model=ChatAnswerResponse,
    summary="Ask a question about a meeting",
    description="Ask MeetMind AI a meeting-scoped question answered only from that meeting's transcript and analysis.",
)
async def chat_with_meeting(
    meeting_id: int,
    payload: ChatRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    chat_service: Annotated[ChatService, Depends(get_chat_service)],
) -> ChatAnswerResponse:
    """Ask a meeting-scoped AI question."""
    answer = await chat_service.ask_question(current_user, meeting_id, payload.message)
    return ChatAnswerResponse(message="Chat response generated successfully.", data=answer)


@router.get(
    "/{meeting_id}/chat/history",
    response_model=ChatHistoryListResponse,
    summary="Get meeting chat history",
    description="Return all saved chat messages for a meeting owned by the authenticated user.",
)
def get_meeting_chat_history(
    meeting_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    chat_service: Annotated[ChatService, Depends(get_chat_service)],
) -> ChatHistoryListResponse:
    """Return meeting chat history."""
    history = chat_service.get_history(current_user, meeting_id)
    return ChatHistoryListResponse(message="Chat history retrieved successfully.", data=history)


@router.delete(
    "/{meeting_id}/chat/history",
    response_model=MessageResponse,
    summary="Delete meeting chat history",
    description="Delete saved chat history for a meeting without deleting the meeting.",
)
def delete_meeting_chat_history(
    meeting_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    chat_service: Annotated[ChatService, Depends(get_chat_service)],
) -> MessageResponse:
    """Delete meeting chat history."""
    chat_service.delete_history(current_user, meeting_id)
    return MessageResponse(message="Chat history deleted successfully.")


@router.get(
    "/{meeting_id}/export/pdf",
    summary="Export meeting as PDF",
    description="Download a professional PDF report for a completed meeting.",
)
def export_meeting_pdf(
    meeting_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    export_service: Annotated[ExportService, Depends(get_export_service)],
) -> StreamingResponse:
    """Export a completed owned meeting as PDF."""
    return build_export_response(export_service.export_pdf(current_user, meeting_id))


@router.get(
    "/{meeting_id}/export/txt",
    summary="Export meeting as TXT",
    description="Download a clean UTF-8 text report for a completed meeting.",
)
def export_meeting_txt(
    meeting_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    export_service: Annotated[ExportService, Depends(get_export_service)],
) -> StreamingResponse:
    """Export a completed owned meeting as TXT."""
    return build_export_response(export_service.export_txt(current_user, meeting_id))


@router.get(
    "/{meeting_id}/export/json",
    summary="Export meeting as JSON",
    description="Download structured meeting data as JSON for a completed meeting.",
)
def export_meeting_json(
    meeting_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    export_service: Annotated[ExportService, Depends(get_export_service)],
) -> StreamingResponse:
    """Export a completed owned meeting as JSON."""
    return build_export_response(export_service.export_json(current_user, meeting_id))


@router.get(
    "/{meeting_id}",
    response_model=MeetingDetailResponse,
    summary="Get meeting details",
    description="Return complete meeting information for a meeting owned by the authenticated user.",
)
def get_meeting(
    meeting_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    meeting_service: Annotated[MeetingService, Depends(get_meeting_service)],
) -> MeetingDetailResponse:
    """Return an owned meeting by ID."""
    meeting = meeting_service.get_meeting(current_user, meeting_id)
    return MeetingDetailResponse(message="Meeting retrieved successfully.", data=meeting)


@router.delete(
    "/{meeting_id}",
    response_model=MessageResponse,
    summary="Delete meeting",
    description="Delete an owned meeting, its database record, and its uploaded files.",
)
def delete_meeting(
    meeting_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    meeting_service: Annotated[MeetingService, Depends(get_meeting_service)],
) -> MessageResponse:
    """Delete an owned meeting and its uploaded file directory."""
    meeting_service.delete_meeting(current_user, meeting_id)
    return MessageResponse(message="Meeting deleted successfully.")
