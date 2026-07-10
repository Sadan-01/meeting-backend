"""Transcript chunking service for long meeting analysis."""

import logging
import re
from dataclasses import dataclass

from fastapi import HTTPException, status

from app.core.config import settings

logger = logging.getLogger(__name__)

AVERAGE_CHARS_PER_TOKEN = 4
SENTENCE_BOUNDARY_PATTERN = re.compile(r"(?<=[.!?])\s+")
SPEAKER_BOUNDARY_PATTERN = re.compile(
    r"(?m)(?=^(?:[A-Z][A-Za-z0-9 ._-]{0,48}|Speaker\s+\d+)\s*:\s+)"
)


@dataclass(frozen=True)
class TranscriptChunk:
    """Ordered transcript chunk prepared for independent analysis."""

    index: int
    total: int
    text: str
    estimated_tokens: int


class ChunkingService:
    """Detect and split large transcripts into intelligent ordered chunks."""

    def should_chunk(self, transcript: str) -> bool:
        """Return whether a transcript should use chunked analysis."""
        if not settings.ENABLE_SMART_CHUNKING:
            return False

        return (
            len(transcript) > settings.MAX_CHUNK_CHARACTERS
            or self.estimate_tokens(transcript) > settings.MAX_TOKENS_PER_CHUNK
        )

    def create_chunks(self, transcript: str) -> list[TranscriptChunk]:
        """Create ordered chunks without cutting sentences whenever possible."""
        normalized_transcript = transcript.strip()
        if not normalized_transcript:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Transcript cannot be empty.",
            )

        logger.info("Transcript chunk creation started")
        segments = self._build_logical_segments(normalized_transcript)
        raw_chunks = self._pack_segments(segments)

        if not raw_chunks:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Transcript chunk generation failed.",
            )

        total_chunks = len(raw_chunks)
        chunks = [
            TranscriptChunk(
                index=index,
                total=total_chunks,
                text=chunk_text,
                estimated_tokens=self.estimate_tokens(chunk_text),
            )
            for index, chunk_text in enumerate(raw_chunks, start=1)
        ]
        logger.info("Transcript chunk creation completed with chunk_count=%s", total_chunks)
        return chunks

    def estimate_tokens(self, text: str) -> int:
        """Estimate token count using a conservative character ratio."""
        return max(1, len(text) // AVERAGE_CHARS_PER_TOKEN)

    def _build_logical_segments(self, transcript: str) -> list[str]:
        """Split transcript by paragraphs, speaker boundaries, then sentence boundaries."""
        segments: list[str] = []
        for paragraph in self._split_paragraphs(transcript):
            speaker_parts = [part.strip() for part in SPEAKER_BOUNDARY_PATTERN.split(paragraph) if part.strip()]
            for speaker_part in speaker_parts or [paragraph]:
                if len(speaker_part) <= settings.MAX_CHUNK_CHARACTERS:
                    segments.append(speaker_part)
                    continue
                segments.extend(self._split_large_segment(speaker_part))
        return [segment for segment in segments if segment]

    def _split_paragraphs(self, transcript: str) -> list[str]:
        """Split transcript into paragraph-like sections."""
        return [paragraph.strip() for paragraph in re.split(r"\n\s*\n+", transcript) if paragraph.strip()]

    def _split_large_segment(self, segment: str) -> list[str]:
        """Split an oversized section by sentence boundaries."""
        sentences = [sentence.strip() for sentence in SENTENCE_BOUNDARY_PATTERN.split(segment) if sentence.strip()]
        split_segments: list[str] = []
        current_segment: list[str] = []
        current_size = 0

        for sentence in sentences:
            sentence_size = len(sentence)
            if current_segment and current_size + sentence_size + 1 > settings.MAX_CHUNK_CHARACTERS:
                split_segments.append(" ".join(current_segment))
                current_segment = [sentence]
                current_size = sentence_size
            else:
                current_segment.append(sentence)
                current_size += sentence_size + 1

        if current_segment:
            split_segments.append(" ".join(current_segment))

        return split_segments or [segment]

    def _pack_segments(self, segments: list[str]) -> list[str]:
        """Pack logical segments into chunk-sized text blocks with overlap."""
        chunks: list[str] = []
        current_parts: list[str] = []
        current_size = 0

        for segment in segments:
            segment_size = len(segment)
            if current_parts and current_size + segment_size + 2 > settings.MAX_CHUNK_CHARACTERS:
                chunk_text = "\n\n".join(current_parts).strip()
                chunks.append(chunk_text)
                overlap_text = self._get_overlap_text(chunk_text)
                current_parts = [overlap_text, segment] if overlap_text else [segment]
                current_size = sum(len(part) for part in current_parts) + (2 * max(0, len(current_parts) - 1))
            else:
                current_parts.append(segment)
                current_size += segment_size + 2

        if current_parts:
            chunks.append("\n\n".join(current_parts).strip())

        return chunks

    def _get_overlap_text(self, chunk_text: str) -> str:
        """Return a sentence-aware trailing overlap for contextual continuity."""
        if settings.CHUNK_OVERLAP_SIZE <= 0:
            return ""

        overlap = chunk_text[-settings.CHUNK_OVERLAP_SIZE :].strip()
        sentence_start = SENTENCE_BOUNDARY_PATTERN.search(overlap)
        if sentence_start:
            return overlap[sentence_start.end() :].strip()
        return overlap
