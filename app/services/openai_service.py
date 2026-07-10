"""OpenAI speech-to-text integration service."""

import logging
from pathlib import Path
from typing import Any

import anyio
from fastapi import HTTPException, status
from openai import APIConnectionError, APIError, APITimeoutError, OpenAI, RateLimitError

from app.core.config import settings

logger = logging.getLogger(__name__)

TRANSIENT_OPENAI_ERRORS = (APITimeoutError, APIConnectionError, RateLimitError)


class OpenAIService:
    """Isolated OpenAI transcription service."""

    def __init__(self) -> None:
        """Initialize the OpenAI client lazily from environment configuration."""
        if not settings.OPENAI_API_KEY:
            self.client: OpenAI | None = None
            return

        self.client = OpenAI(
            api_key=settings.OPENAI_API_KEY,
            timeout=settings.OPENAI_REQUEST_TIMEOUT_SECONDS,
        )

    async def transcribe_audio(self, audio_path: Path) -> str:
        """Transcribe an audio file with retry handling for transient failures."""
        if self.client is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="AI transcription is not configured.",
            )

        for attempt in range(1, settings.TRANSCRIPTION_MAX_RETRIES + 1):
            try:
                transcript = await anyio.to_thread.run_sync(self._transcribe_sync, audio_path)
                return self._validate_transcript(transcript)
            except TRANSIENT_OPENAI_ERRORS as exc:
                logger.warning("Transient OpenAI transcription failure on attempt %s", attempt)
                if attempt >= settings.TRANSCRIPTION_MAX_RETRIES:
                    raise self._openai_http_error("AI transcription temporarily failed.") from exc
                await anyio.sleep(min(2**attempt, 10))
            except APIError as exc:
                logger.exception("OpenAI API failed during transcription")
                raise self._openai_http_error("AI transcription failed.") from exc

        raise self._openai_http_error("AI transcription failed.")

    def _transcribe_sync(self, audio_path: Path) -> Any:
        """Run the synchronous OpenAI transcription call."""
        if self.client is None:
            raise RuntimeError("OpenAI client is not configured.")

        with audio_path.open("rb") as audio_file:
            return self.client.audio.transcriptions.create(
                model=settings.OPENAI_TRANSCRIPTION_MODEL,
                file=audio_file,
                response_format="text",
            )

    def _validate_transcript(self, response: Any) -> str:
        """Validate and normalize the OpenAI transcription response."""
        transcript = response if isinstance(response, str) else getattr(response, "text", None)
        if not isinstance(transcript, str) or not transcript.strip():
            logger.error("OpenAI returned an empty transcription response")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="AI transcription returned no text.",
            )
        return transcript.strip()

    def _openai_http_error(self, message: str) -> HTTPException:
        """Return a safe HTTP error for OpenAI failures."""
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=message,
        )
