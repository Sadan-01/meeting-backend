"""Merge multiple chunk analyses into final meeting intelligence."""

import json
import logging
from typing import Any

import anyio
from fastapi import HTTPException, status
from openai import APIConnectionError, APIError, APITimeoutError, OpenAI, RateLimitError
from pydantic import ValidationError

from app.core.config import settings
from app.prompts.meeting_analysis import MEETING_ANALYSIS_SYSTEM_PROMPT
from app.schemas.analysis import AnalysisActionItem, AnalysisDeadline, AnalysisResult

logger = logging.getLogger(__name__)

TRANSIENT_MERGE_ERRORS = (APITimeoutError, APIConnectionError, RateLimitError)


class SummaryMergerService:
    """Merge chunk-level structured results into one final analysis."""

    def __init__(self) -> None:
        """Initialize the OpenAI client when configured."""
        self.client = (
            OpenAI(api_key=settings.OPENAI_API_KEY, timeout=settings.OPENAI_REQUEST_TIMEOUT_SECONDS)
            if settings.OPENAI_API_KEY
            else None
        )

    async def merge(self, partial_results: list[AnalysisResult]) -> AnalysisResult:
        """Merge ordered chunk analyses and return final structured output."""
        if not partial_results:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="No chunk summaries were generated.",
            )

        if len(partial_results) == 1:
            return partial_results[0]

        logger.info("Chunk summary merge started for partial_count=%s", len(partial_results))
        if self.client is None:
            merged_result = self._merge_deterministically(partial_results)
            logger.info("Chunk summary merge completed with deterministic fallback")
            return merged_result

        for attempt in range(1, settings.TRANSCRIPTION_MAX_RETRIES + 1):
            try:
                raw_response = await anyio.to_thread.run_sync(self._merge_sync, partial_results)
                merged_result = self._parse_analysis_response(raw_response)
                logger.info("Chunk summary merge completed")
                return merged_result
            except TRANSIENT_MERGE_ERRORS as exc:
                logger.warning("Transient chunk merge failure attempt=%s", attempt)
                if attempt >= settings.TRANSCRIPTION_MAX_RETRIES:
                    raise self._safe_ai_error("Summary merge temporarily failed.") from exc
                await anyio.sleep(min(2**attempt, 10))
            except APIError as exc:
                logger.exception("OpenAI API failed during summary merge")
                raise self._safe_ai_error("Summary merge failed.") from exc

        raise self._safe_ai_error("Summary merge failed.")

    def _merge_sync(self, partial_results: list[AnalysisResult]) -> str:
        """Run the synchronous OpenAI request for final summary merge."""
        if self.client is None:
            raise RuntimeError("OpenAI client is not configured.")

        payload = [result.model_dump() for result in partial_results]
        prompt = f"""
Merge these ordered meeting chunk analyses into one final JSON object.
Remove duplicates, preserve chronology, consolidate participants, action items,
deadlines, decisions, risks, and next steps. Generate one final executive_summary.
Return exactly the same JSON structure.

Chunk analyses:
{json.dumps(payload, ensure_ascii=False)}
""".strip()
        response = self.client.chat.completions.create(
            model=settings.OPENAI_ANALYSIS_MODEL,
            messages=[
                {"role": "system", "content": MEETING_ANALYSIS_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
        )
        content = response.choices[0].message.content
        if not content:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Summary merge returned no content.",
            )
        return content

    def _merge_deterministically(self, partial_results: list[AnalysisResult]) -> AnalysisResult:
        """Merge partial results locally when provider merge is unavailable."""
        summaries = [result.executive_summary for result in partial_results if result.executive_summary]
        return AnalysisResult(
            executive_summary=" ".join(summaries),
            key_points=self._dedupe_strings(item for result in partial_results for item in result.key_points),
            action_items=self._dedupe_action_items(
                item for result in partial_results for item in result.action_items
            ),
            participants=self._dedupe_strings(item for result in partial_results for item in result.participants),
            key_decisions=self._dedupe_strings(item for result in partial_results for item in result.key_decisions),
            deadlines=self._dedupe_deadlines(item for result in partial_results for item in result.deadlines),
            risks=self._dedupe_strings(item for result in partial_results for item in result.risks),
            next_steps=self._dedupe_strings(item for result in partial_results for item in result.next_steps),
        )

    def _parse_analysis_response(self, response_text: str) -> AnalysisResult:
        """Parse and validate merged analysis JSON."""
        try:
            payload = json.loads(self._strip_json_response(response_text))
            return AnalysisResult.model_validate(payload)
        except (json.JSONDecodeError, ValidationError) as exc:
            logger.exception("Merged analysis response failed structured validation")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Summary merge returned invalid structured data.",
            ) from exc

    def _dedupe_strings(self, values: Any) -> list[str]:
        """Dedupe strings while preserving order."""
        seen: set[str] = set()
        deduped_values: list[str] = []
        for value in values:
            normalized_value = value.strip()
            key = normalized_value.lower()
            if normalized_value and key not in seen:
                seen.add(key)
                deduped_values.append(normalized_value)
        return deduped_values

    def _dedupe_action_items(self, values: Any) -> list[AnalysisActionItem]:
        """Dedupe action items by task, assignee, and deadline."""
        seen: set[tuple[str, str | None, str | None]] = set()
        deduped_values: list[AnalysisActionItem] = []
        for value in values:
            key = (value.task.lower(), value.assignee, value.deadline)
            if key not in seen:
                seen.add(key)
                deduped_values.append(value)
        return deduped_values

    def _dedupe_deadlines(self, values: Any) -> list[AnalysisDeadline]:
        """Dedupe deadlines by item, owner, and date."""
        seen: set[tuple[str, str | None, str | None]] = set()
        deduped_values: list[AnalysisDeadline] = []
        for value in values:
            key = (value.item.lower(), value.owner, value.deadline)
            if key not in seen:
                seen.add(key)
                deduped_values.append(value)
        return deduped_values

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
