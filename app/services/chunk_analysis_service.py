"""OpenAI-powered analysis for individual transcript chunks."""

import json
import logging
from typing import Any

import anyio
from fastapi import HTTPException, status
from openai import APIConnectionError, APIError, APITimeoutError, OpenAI, RateLimitError
from pydantic import ValidationError

from app.core.config import settings
from app.prompts.meeting_analysis import MEETING_ANALYSIS_SYSTEM_PROMPT, build_meeting_analysis_prompt
from app.schemas.analysis import AnalysisResult
from app.services.chunking_service import TranscriptChunk

logger = logging.getLogger(__name__)

TRANSIENT_CHUNK_ANALYSIS_ERRORS = (APITimeoutError, APIConnectionError, RateLimitError)


class ChunkAnalysisService:
    """Analyze one transcript chunk and return structured JSON data."""

    def __init__(self) -> None:
        """Initialize the OpenAI client when configured."""
        self.client = (
            OpenAI(api_key=settings.OPENAI_API_KEY, timeout=settings.OPENAI_REQUEST_TIMEOUT_SECONDS)
            if settings.OPENAI_API_KEY
            else None
        )

    async def analyze_chunk(self, chunk: TranscriptChunk) -> AnalysisResult:
        """Analyze a single transcript chunk with retry handling."""
        if self.client is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="AI analysis is not configured.",
            )

        logger.info("Chunk analysis started for chunk=%s total=%s", chunk.index, chunk.total)
        for attempt in range(1, settings.TRANSCRIPTION_MAX_RETRIES + 1):
            try:
                raw_response = await anyio.to_thread.run_sync(self._analyze_chunk_sync, chunk)
                result = self._parse_analysis_response(raw_response)
                logger.info("Chunk analysis completed for chunk=%s total=%s", chunk.index, chunk.total)
                return result
            except TRANSIENT_CHUNK_ANALYSIS_ERRORS as exc:
                logger.warning("Transient chunk analysis failure chunk=%s attempt=%s", chunk.index, attempt)
                if attempt >= settings.TRANSCRIPTION_MAX_RETRIES:
                    raise self._safe_ai_error("Chunk analysis temporarily failed.") from exc
                await anyio.sleep(min(2**attempt, 10))
            except APIError as exc:
                logger.exception("OpenAI API failed during chunk analysis")
                raise self._safe_ai_error("Chunk analysis failed.") from exc

        raise self._safe_ai_error("Chunk analysis failed.")

    def _analyze_chunk_sync(self, chunk: TranscriptChunk) -> str:
        """Run the synchronous OpenAI request for a chunk."""
        if self.client is None:
            raise RuntimeError("OpenAI client is not configured.")

        prompt = (
            f"Analyze transcript chunk {chunk.index} of {chunk.total}. "
            "Return structured JSON for this chunk only.\n\n"
            f"{build_meeting_analysis_prompt(chunk.text)}"
        )
        response = self.client.chat.completions.create(
            model=settings.OPENAI_ANALYSIS_MODEL,
            messages=[
                {"role": "system", "content": MEETING_ANALYSIS_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        content = response.choices[0].message.content
        if not content:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Chunk analysis returned no content.",
            )
        return content

    def _parse_analysis_response(self, response_text: str) -> AnalysisResult:
        """Parse and validate chunk analysis JSON."""
        try:
            payload = json.loads(self._strip_json_response(response_text))
            return AnalysisResult.model_validate(payload)
        except (json.JSONDecodeError, ValidationError) as exc:
            logger.exception("Chunk analysis response failed structured validation")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Chunk analysis returned invalid structured data.",
            ) from exc

    def _strip_json_response(self, response_text: str) -> str:
        """Remove markdown fences when present."""
        stripped_response = response_text.strip()
        if stripped_response.startswith("```json"):
            return stripped_response.removeprefix("```json").removesuffix("```").strip()
        if stripped_response.startswith("```"):
            return stripped_response.removeprefix("```").removesuffix("```").strip()
        return stripped_response

    def _safe_ai_error(self, message: str) -> HTTPException:
        """Return a safe provider error."""
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=message)
