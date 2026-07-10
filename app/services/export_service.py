"""Meeting export generation service."""

import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from typing import Any

from fastapi import HTTPException, status
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import ListFlowable, ListItem, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.models.action_item import ActionItem
from app.models.chat_history import ChatHistory
from app.models.enums import ProcessingStatus
from app.models.meeting import Meeting
from app.models.user import User

logger = logging.getLogger(__name__)

EXPORT_TITLE_PREFIX = "Meeting"
FILENAME_SAFE_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True)
class ExportFile:
    """Generated export file content and response metadata."""

    content: bytes
    filename: str
    media_type: str


class ExportService:
    """Generate meeting exports in PDF, TXT, and JSON formats."""

    def __init__(self, db: Session) -> None:
        """Initialize the export service with a database session."""
        self.db = db

    def export_pdf(self, user: User, meeting_id: int) -> ExportFile:
        """Generate a professional PDF export for a completed meeting."""
        started_at = time.perf_counter()
        meeting = self._get_exportable_meeting(user.id, meeting_id)
        logger.info("Export started format=pdf meeting_id=%s", meeting_id)

        try:
            content = self._build_pdf(meeting)
        except Exception as exc:
            logger.exception("PDF generation failed for meeting_id=%s", meeting_id)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="PDF export generation failed.",
            ) from exc

        logger.info("Export completed format=pdf meeting_id=%s duration_ms=%s", meeting_id, self._elapsed_ms(started_at))
        return ExportFile(content=content, filename=self._build_filename(meeting, "pdf"), media_type="application/pdf")

    def export_txt(self, user: User, meeting_id: int) -> ExportFile:
        """Generate a UTF-8 text export for a completed meeting."""
        started_at = time.perf_counter()
        meeting = self._get_exportable_meeting(user.id, meeting_id)
        logger.info("Export started format=txt meeting_id=%s", meeting_id)
        content = self._build_txt(meeting).encode("utf-8")
        logger.info("Export completed format=txt meeting_id=%s duration_ms=%s", meeting_id, self._elapsed_ms(started_at))
        return ExportFile(content=content, filename=self._build_filename(meeting, "txt"), media_type="text/plain; charset=utf-8")

    def export_json(self, user: User, meeting_id: int) -> ExportFile:
        """Generate a structured JSON export for a completed meeting."""
        started_at = time.perf_counter()
        meeting = self._get_exportable_meeting(user.id, meeting_id)
        logger.info("Export started format=json meeting_id=%s", meeting_id)
        content = json.dumps(self._build_json_payload(meeting), ensure_ascii=False, indent=2).encode("utf-8")
        logger.info("Export completed format=json meeting_id=%s duration_ms=%s", meeting_id, self._elapsed_ms(started_at))
        return ExportFile(content=content, filename=self._build_filename(meeting, "json"), media_type="application/json")

    def _get_exportable_meeting(self, user_id: int, meeting_id: int) -> Meeting:
        """Return an owned completed meeting with export relationships loaded."""
        meeting = self.db.scalar(
            select(Meeting)
            .options(selectinload(Meeting.action_items), selectinload(Meeting.chat_history))
            .where(Meeting.id == meeting_id, Meeting.user_id == user_id)
        )
        if meeting is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found.")

        if meeting.processing_status != ProcessingStatus.COMPLETED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Meeting must be fully processed before export.",
            )

        return meeting

    def _build_pdf(self, meeting: Meeting) -> bytes:
        """Build a professional multi-page PDF report."""
        buffer = BytesIO()
        document = SimpleDocTemplate(
            buffer,
            pagesize=LETTER,
            rightMargin=0.75 * inch,
            leftMargin=0.75 * inch,
            topMargin=0.75 * inch,
            bottomMargin=0.75 * inch,
            title=meeting.title,
        )
        styles = self._pdf_styles()
        story: list[Any] = [
            Paragraph("MeetMind AI Meeting Report", styles["Title"]),
            Paragraph(self._escape(meeting.title), styles["Subtitle"]),
            Spacer(1, 0.2 * inch),
        ]

        story.extend(self._pdf_meeting_information(meeting, styles))
        story.extend(self._pdf_section("Executive Summary", meeting.executive_summary, styles))
        story.extend(self._pdf_list_section("Participants", meeting.participants or [], styles))
        story.extend(self._pdf_list_section("Key Points", meeting.key_points or [], styles))
        story.extend(self._pdf_list_section("Key Decisions", meeting.key_decisions or [], styles))
        story.extend(self._pdf_action_items(meeting.action_items, styles))
        story.extend(self._pdf_deadlines(meeting.deadlines or [], styles))
        story.extend(self._pdf_list_section("Risks", meeting.risks or [], styles))
        story.extend(self._pdf_list_section("Next Steps", meeting.next_steps or [], styles))

        if settings.PDF_INCLUDE_TRANSCRIPT and meeting.transcript:
            story.append(PageBreak())
            story.extend(self._pdf_section("Transcript", meeting.transcript, styles))

        if settings.PDF_INCLUDE_CHAT_HISTORY and meeting.chat_history:
            story.append(PageBreak())
            story.extend(self._pdf_chat_history(meeting.chat_history, styles))

        document.build(story, onFirstPage=self._draw_pdf_footer, onLaterPages=self._draw_pdf_footer)
        return buffer.getvalue()

    def _build_txt(self, meeting: Meeting) -> str:
        """Build a readable text export."""
        sections = [
            self._txt_heading("MeetMind AI Meeting Report"),
            f"Meeting Title: {meeting.title}",
            f"Meeting Date: {self._format_datetime(meeting.created_at)}",
            f"Generated At: {self._format_datetime(self._now())}",
            "",
            self._txt_section("Participants", meeting.participants or []),
            self._txt_section("Executive Summary", meeting.executive_summary or ""),
            self._txt_section("Key Points", meeting.key_points or []),
            self._txt_section("Key Decisions", meeting.key_decisions or []),
            self._txt_section("Action Items", self._serialize_action_items(meeting.action_items)),
            self._txt_section("Deadlines", meeting.deadlines or []),
            self._txt_section("Risks", meeting.risks or []),
            self._txt_section("Next Steps", meeting.next_steps or []),
        ]
        if settings.PDF_INCLUDE_TRANSCRIPT and meeting.transcript:
            sections.append(self._txt_section("Transcript", meeting.transcript))
        if settings.PDF_INCLUDE_CHAT_HISTORY and meeting.chat_history:
            sections.append(self._txt_section("Chat History", self._serialize_chat_history(meeting.chat_history)))
        sections.append(settings.EXPORT_BRANDING)
        return "\n\n".join(section for section in sections if section)

    def _build_json_payload(self, meeting: Meeting) -> dict[str, Any]:
        """Build a structured JSON payload suitable for integrations."""
        payload: dict[str, Any] = {
            "meeting": {
                "id": meeting.id,
                "title": meeting.title,
                "meeting_date": self._format_datetime(meeting.created_at),
                "processing_status": meeting.processing_status.value,
                "duration_seconds": meeting.duration_seconds,
            },
            "generated_at": self._format_datetime(self._now()),
            "branding": settings.EXPORT_BRANDING,
            "participants": meeting.participants or [],
            "executive_summary": meeting.executive_summary,
            "key_points": meeting.key_points or [],
            "key_decisions": meeting.key_decisions or [],
            "action_items": self._serialize_action_items(meeting.action_items),
            "deadlines": meeting.deadlines or [],
            "risks": meeting.risks or [],
            "next_steps": meeting.next_steps or [],
        }
        if settings.PDF_INCLUDE_TRANSCRIPT:
            payload["transcript"] = meeting.transcript
        if settings.PDF_INCLUDE_CHAT_HISTORY:
            payload["chat_history"] = self._serialize_chat_history(meeting.chat_history)
        return payload

    def _pdf_styles(self) -> dict[str, ParagraphStyle]:
        """Return reusable PDF styles."""
        base_styles = getSampleStyleSheet()
        return {
            "Title": ParagraphStyle("MeetMindTitle", parent=base_styles["Title"], fontName="Helvetica-Bold", fontSize=22, leading=28, alignment=TA_CENTER, textColor=colors.HexColor("#1F2937"), spaceAfter=8),
            "Subtitle": ParagraphStyle("MeetMindSubtitle", parent=base_styles["Heading2"], fontName="Helvetica", fontSize=14, leading=18, alignment=TA_CENTER, textColor=colors.HexColor("#4B5563"), spaceAfter=16),
            "Heading": ParagraphStyle("MeetMindHeading", parent=base_styles["Heading2"], fontName="Helvetica-Bold", fontSize=14, leading=18, textColor=colors.HexColor("#111827"), spaceBefore=14, spaceAfter=8),
            "Body": ParagraphStyle("MeetMindBody", parent=base_styles["BodyText"], fontName="Helvetica", fontSize=10, leading=14, textColor=colors.HexColor("#1F2937"), spaceAfter=6),
            "Small": ParagraphStyle("MeetMindSmall", parent=base_styles["BodyText"], fontName="Helvetica", fontSize=8, leading=10, textColor=colors.HexColor("#6B7280")),
        }

    def _pdf_meeting_information(self, meeting: Meeting, styles: dict[str, ParagraphStyle]) -> list[Any]:
        """Build the meeting information PDF table."""
        data = [
            ["Meeting Date", self._format_datetime(meeting.created_at)],
            ["Duration", f"{meeting.duration_seconds or 0} seconds" if meeting.duration_seconds else "Unavailable"],
            ["Generated At", self._format_datetime(self._now())],
        ]
        table = Table(data, colWidths=[1.6 * inch, 4.8 * inch])
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F3F4F6")),
                    ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#111827")),
                    ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D1D5DB")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("PADDING", (0, 0), (-1, -1), 7),
                ]
            )
        )
        return [Paragraph("Meeting Information", styles["Heading"]), table, Spacer(1, 0.1 * inch)]

    def _pdf_section(self, title: str, content: str | None, styles: dict[str, ParagraphStyle]) -> list[Any]:
        """Build a PDF text section."""
        if not content:
            return []
        paragraphs = [Paragraph(title, styles["Heading"])]
        for block in str(content).splitlines() or [str(content)]:
            if block.strip():
                paragraphs.append(Paragraph(self._escape(block.strip()), styles["Body"]))
        return paragraphs

    def _pdf_list_section(self, title: str, items: list[Any], styles: dict[str, ParagraphStyle]) -> list[Any]:
        """Build a PDF bullet-list section."""
        if not items:
            return []
        flowables = [Paragraph(title, styles["Heading"])]
        flowables.append(
            ListFlowable(
                [ListItem(Paragraph(self._escape(str(item)), styles["Body"])) for item in items],
                bulletType="bullet",
                leftIndent=18,
            )
        )
        return flowables

    def _pdf_action_items(self, action_items: list[ActionItem], styles: dict[str, ParagraphStyle]) -> list[Any]:
        """Build the PDF action item section."""
        serialized_items = self._serialize_action_items(action_items)
        return self._pdf_list_section(
            "Action Items",
            [
                f"{item['task']} | Assignee: {item['assignee'] or 'Unassigned'} | Deadline: {item['deadline'] or 'No deadline'}"
                for item in serialized_items
            ],
            styles,
        )

    def _pdf_deadlines(self, deadlines: list[dict[str, Any]], styles: dict[str, ParagraphStyle]) -> list[Any]:
        """Build the PDF deadlines section."""
        return self._pdf_list_section("Deadlines", [json.dumps(item, ensure_ascii=False) for item in deadlines], styles)

    def _pdf_chat_history(self, history: list[ChatHistory], styles: dict[str, ParagraphStyle]) -> list[Any]:
        """Build the PDF chat history section."""
        flowables = [Paragraph("Chat History", styles["Heading"])]
        for item in sorted(history, key=lambda chat: chat.created_at):
            flowables.append(Paragraph(f"Q: {self._escape(item.question)}", styles["Body"]))
            flowables.append(Paragraph(f"A: {self._escape(item.answer)}", styles["Body"]))
        return flowables

    def _draw_pdf_footer(self, canvas: Any, document: SimpleDocTemplate) -> None:
        """Draw PDF footer with branding, timestamp, and page number."""
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        footer = f"{settings.EXPORT_BRANDING} | {self._format_datetime(self._now())} | Page {document.page}"
        canvas.drawCentredString(LETTER[0] / 2, 0.4 * inch, footer)
        canvas.restoreState()

    def _txt_heading(self, title: str) -> str:
        """Return a plain text heading."""
        return f"{title}\n{'=' * len(title)}"

    def _txt_section(self, title: str, content: Any) -> str:
        """Return a formatted plain text section."""
        if content in (None, "", []):
            return ""
        lines = [title, "-" * len(title)]
        if isinstance(content, list):
            lines.extend(f"- {item}" for item in content)
        else:
            lines.append(str(content))
        return "\n".join(lines)

    def _serialize_action_items(self, action_items: list[ActionItem]) -> list[dict[str, Any]]:
        """Serialize action items for TXT and JSON exports."""
        return [
            {
                "task": item.task,
                "assignee": item.assignee,
                "deadline": self._format_datetime(item.deadline) if item.deadline else None,
                "completed": item.completed,
            }
            for item in sorted(action_items, key=lambda action_item: action_item.created_at)
        ]

    def _serialize_chat_history(self, history: list[ChatHistory]) -> list[dict[str, str]]:
        """Serialize chat history for exports."""
        return [
            {
                "question": item.question,
                "answer": item.answer,
                "created_at": self._format_datetime(item.created_at),
            }
            for item in sorted(history, key=lambda chat: chat.created_at)
        ]

    def _build_filename(self, meeting: Meeting, extension: str) -> str:
        """Build a safe downloadable filename."""
        title = FILENAME_SAFE_PATTERN.sub("_", meeting.title).strip("._") or "Meeting"
        date_value = meeting.created_at.date().isoformat()
        return f"{EXPORT_TITLE_PREFIX}_{title}_{date_value}.{extension}"

    def _format_datetime(self, value: datetime) -> str:
        """Return an ISO datetime string."""
        return value.astimezone(UTC).isoformat() if value.tzinfo else value.replace(tzinfo=UTC).isoformat()

    def _now(self) -> datetime:
        """Return the current UTC datetime."""
        return datetime.now(UTC)

    def _elapsed_ms(self, started_at: float) -> int:
        """Return elapsed milliseconds."""
        return round((time.perf_counter() - started_at) * 1000)

    def _escape(self, value: str) -> str:
        """Escape text for ReportLab paragraph markup."""
        return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
