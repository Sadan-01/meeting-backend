"""Meeting-scoped AI chat service."""

import logging
import time
from collections.abc import Iterable

import anyio
from fastapi import HTTPException, status
from openai import APIConnectionError, APIError, APITimeoutError, OpenAI, RateLimitError
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.models.action_item import ActionItem
from app.models.chat_history import ChatHistory
from app.models.meeting import Meeting
from app.models.user import User
from app.schemas.chat import ChatAnswerData, ChatHistoryListData, ChatHistoryResponse
from app.services.chunking_service import ChunkingService, TranscriptChunk
from app.utils.prompts import MEETING_CHAT_SYSTEM_PROMPT, build_meeting_chat_prompt

logger = logging.getLogger(__name__)

TRANSIENT_CHAT_ERRORS = (APITimeoutError, APIConnectionError, RateLimitError)


class ChatService:
    """Generate and persist meeting-scoped AI chat responses."""

    def __init__(self, db: Session, chunking_service: ChunkingService | None = None) -> None:
        """Initialize the service with a database session."""
        self.db = db
        self.chunking_service = chunking_service or ChunkingService()
        self.client = (
            OpenAI(api_key=settings.OPENAI_API_KEY, timeout=settings.OPENAI_REQUEST_TIMEOUT_SECONDS)
            if settings.OPENAI_API_KEY
            else None
        )

    async def ask_question(self, user: User, meeting_id: int, message: str) -> ChatAnswerData:
        """Answer a user's question using only the owned meeting context."""
        meeting = self._get_owned_meeting(user.id, meeting_id)
        self._validate_chat_ready(meeting)

        logger.info("Meeting chat started for meeting_id=%s", meeting_id)
        recent_history = self._get_recent_history(meeting_id)
        meeting_context = self._build_meeting_context(meeting, message)
        prompt = build_meeting_chat_prompt(
            meeting_context=meeting_context,
            recent_history=self._format_recent_history(recent_history),
            user_message=message,
        )

        answer = await self._generate_answer(prompt)
        self._save_conversation(meeting_id, message, answer)
        logger.info("Meeting chat response generated and saved for meeting_id=%s", meeting_id)
        return ChatAnswerData(answer=answer)

    def get_history(self, user: User, meeting_id: int) -> ChatHistoryListData:
        """Return all conversation history for an owned meeting, oldest first."""
        self._get_owned_meeting(user.id, meeting_id)
        history = self.db.scalars(
            select(ChatHistory).where(ChatHistory.meeting_id == meeting_id).order_by(ChatHistory.created_at.asc())
        ).all()
        return ChatHistoryListData(items=[ChatHistoryResponse.model_validate(item) for item in history])

    def delete_history(self, user: User, meeting_id: int) -> None:
        """Delete conversation history for an owned meeting only."""
        self._get_owned_meeting(user.id, meeting_id)
        self.db.execute(delete(ChatHistory).where(ChatHistory.meeting_id == meeting_id))
        self.db.commit()
        logger.info("Meeting chat history deleted for meeting_id=%s", meeting_id)

    async def _generate_answer(self, prompt: str) -> str:
        """Generate a chat answer with retry handling."""
        if self.client is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="AI chat is not configured.",
            )

        for attempt in range(1, settings.TRANSCRIPTION_MAX_RETRIES + 1):
            started_at = time.perf_counter()
            try:
                answer = await anyio.to_thread.run_sync(self._generate_answer_sync, prompt)
                latency_ms = round((time.perf_counter() - started_at) * 1000)
                logger.info("OpenAI chat response generated in %sms", latency_ms)
                return self._validate_answer(answer)
            except TRANSIENT_CHAT_ERRORS as exc:
                logger.warning("Transient OpenAI chat failure on attempt=%s", attempt)
                if attempt >= settings.TRANSCRIPTION_MAX_RETRIES:
                    raise self._safe_ai_error("AI chat temporarily failed.") from exc
                await anyio.sleep(min(2**attempt, 10))
            except APIError as exc:
                logger.exception("OpenAI API failed during meeting chat")
                raise self._safe_ai_error("AI chat failed.") from exc

        raise self._safe_ai_error("AI chat failed.")

    def _generate_answer_sync(self, prompt: str) -> str:
        """Run the synchronous OpenAI chat request."""
        if self.client is None:
            raise RuntimeError("OpenAI client is not configured.")

        response = self.client.chat.completions.create(
            model=settings.CHAT_MODEL,
            messages=[
                {"role": "system", "content": MEETING_CHAT_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=settings.CHAT_TEMPERATURE,
        )
        content = response.choices[0].message.content
        if not content:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="AI chat returned no answer.",
            )
        return content

    def _build_meeting_context(self, meeting: Meeting, message: str) -> str:
        """Build optimized meeting context for a question."""
        sections = [
            f"Title: {meeting.title}",
            self._format_analysis_context(meeting),
            self._format_action_items(meeting.action_items),
            self._select_transcript_context(meeting.transcript or "", message),
        ]
        context = "\n\n".join(section for section in sections if section)
        return context[: settings.MAX_CONTEXT_LENGTH]

    def _format_analysis_context(self, meeting: Meeting) -> str:
        """Format stored structured analysis for chat context."""
        parts = [
            ("Executive Summary", meeting.executive_summary),
            ("Key Points", meeting.key_points),
            ("Participants", meeting.participants),
            ("Key Decisions", meeting.key_decisions),
            ("Deadlines", meeting.deadlines),
            ("Risks", meeting.risks),
            ("Next Steps", meeting.next_steps),
        ]
        formatted_parts: list[str] = []
        for label, value in parts:
            if value:
                formatted_parts.append(f"{label}: {value}")
        return "\n".join(formatted_parts)

    def _format_action_items(self, action_items: Iterable[ActionItem]) -> str:
        """Format action items for chat context."""
        formatted_items = []
        for item in action_items:
            assignee = item.assignee or "Unassigned"
            deadline = item.deadline.isoformat() if item.deadline else "No deadline"
            formatted_items.append(f"- {item.task} | Assignee: {assignee} | Deadline: {deadline}")
        if not formatted_items:
            return ""
        return "Action Items:\n" + "\n".join(formatted_items)

    def _select_transcript_context(self, transcript: str, message: str) -> str:
        """Select relevant transcript text, using chunking for long transcripts."""
        if not transcript.strip():
            return ""

        available_context = max(settings.MAX_CONTEXT_LENGTH // 2, 1000)
        if not self.chunking_service.should_chunk(transcript):
            return f"Transcript Excerpt:\n{transcript[:available_context]}"

        chunks = self.chunking_service.create_chunks(transcript)
        relevant_chunks = self._select_relevant_chunks(chunks, message)
        transcript_context = "\n\n".join(chunk.text for chunk in relevant_chunks)
        return f"Relevant Transcript Sections:\n{transcript_context[:available_context]}"

    def _select_relevant_chunks(self, chunks: list[TranscriptChunk], message: str) -> list[TranscriptChunk]:
        """Select the most relevant transcript chunks by lexical overlap."""
        query_terms = self._tokenize(message)
        if not query_terms:
            return chunks[:2]

        scored_chunks = []
        for chunk in chunks:
            chunk_terms = self._tokenize(chunk.text)
            score = len(query_terms.intersection(chunk_terms))
            scored_chunks.append((score, chunk.index, chunk))

        selected = [chunk for score, _, chunk in sorted(scored_chunks, key=lambda item: (-item[0], item[1])) if score > 0]
        return sorted((selected or chunks[:2])[:3], key=lambda chunk: chunk.index)

    def _format_recent_history(self, history: list[ChatHistory]) -> str:
        """Format recent conversation turns for context."""
        return "\n".join(f"Q: {item.question}\nA: {item.answer}" for item in history)

    def _get_recent_history(self, meeting_id: int) -> list[ChatHistory]:
        """Return recent chat history in chronological order."""
        history = self.db.scalars(
            select(ChatHistory)
            .where(ChatHistory.meeting_id == meeting_id)
            .order_by(ChatHistory.created_at.desc())
            .limit(settings.MAX_CHAT_HISTORY)
        ).all()
        return list(reversed(history))

    def _save_conversation(self, meeting_id: int, question: str, answer: str) -> None:
        """Persist a question and answer pair."""
        self.db.add(ChatHistory(meeting_id=meeting_id, question=question, answer=answer))
        self.db.commit()

    def _get_owned_meeting(self, user_id: int, meeting_id: int) -> Meeting:
        """Return an owned meeting with analysis relationships loaded."""
        meeting = self.db.scalar(
            select(Meeting)
            .options(selectinload(Meeting.action_items))
            .where(Meeting.id == meeting_id, Meeting.user_id == user_id)
        )
        if meeting is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Meeting not found.",
            )
        return meeting

    def _validate_chat_ready(self, meeting: Meeting) -> None:
        """Validate that meeting context exists for chat."""
        if not meeting.transcript:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Meeting transcript not found.",
            )

    def _validate_answer(self, answer: str) -> str:
        """Validate the generated chat answer."""
        normalized_answer = answer.strip()
        if not normalized_answer:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="AI chat returned no answer.",
            )
        return normalized_answer

    def _tokenize(self, text: str) -> set[str]:
        """Tokenize text for lightweight relevance scoring."""
        return {token for token in (part.strip(".,!?;:()[]{}\"'").lower() for part in text.split()) if len(token) > 2}

    def _safe_ai_error(self, message: str) -> HTTPException:
        """Return a safe AI provider error."""
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=message)
