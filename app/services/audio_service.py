"""Audio preparation service for meeting transcription."""

import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException, status

from app.core.config import settings
from app.utils.upload import ALLOWED_FILE_EXTENSIONS

logger = logging.getLogger(__name__)

MP4_EXTENSION = ".mp4"
TRANSCRIPTION_AUDIO_EXTENSION = ".m4a"


@dataclass(frozen=True)
class PreparedAudio:
    """Audio file prepared for transcription."""

    file_path: Path
    duration_seconds: int | None


class AudioService:
    """Prepare uploaded media files for speech-to-text processing."""

    def prepare_for_transcription(self, source_path: Path, file_extension: str) -> PreparedAudio:
        """Validate media and return an audio file ready for transcription."""
        self._validate_media_file(source_path, file_extension)
        audio_path = self._extract_audio_from_mp4(source_path) if file_extension == MP4_EXTENSION else source_path
        duration_seconds = self.calculate_duration(audio_path)
        self._validate_duration(duration_seconds)
        return PreparedAudio(file_path=audio_path, duration_seconds=duration_seconds)

    def calculate_duration(self, media_path: Path) -> int | None:
        """Calculate media duration in seconds using FFprobe."""
        command = [
            settings.FFPROBE_BINARY,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(media_path),
        ]

        try:
            result = subprocess.run(command, capture_output=True, text=True, check=True, timeout=30)
        except FileNotFoundError as exc:
            logger.exception("FFprobe executable was not found")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Audio processing is not configured.",
            ) from exc
        except subprocess.CalledProcessError as exc:
            logger.exception("FFprobe failed for uploaded media")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unable to validate uploaded media.",
            ) from exc
        except subprocess.TimeoutExpired as exc:
            logger.exception("FFprobe timed out while validating media")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Audio validation timed out.",
            ) from exc

        try:
            duration = float(json.loads(result.stdout)["format"]["duration"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            logger.warning("FFprobe did not return a valid duration")
            return None

        return max(0, round(duration))

    def _extract_audio_from_mp4(self, source_path: Path) -> Path:
        """Extract audio from an MP4 file using FFmpeg."""
        output_path = source_path.with_name(f"{source_path.stem}_audio{TRANSCRIPTION_AUDIO_EXTENSION}")
        command = [
            settings.FFMPEG_BINARY,
            "-y",
            "-i",
            str(source_path),
            "-vn",
            "-acodec",
            "aac",
            str(output_path),
        ]

        try:
            subprocess.run(command, capture_output=True, text=True, check=True, timeout=600)
        except FileNotFoundError as exc:
            logger.exception("FFmpeg executable was not found")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Audio processing is not configured.",
            ) from exc
        except subprocess.CalledProcessError as exc:
            logger.exception("FFmpeg failed to extract audio from MP4")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to extract audio from uploaded video.",
            ) from exc
        except subprocess.TimeoutExpired as exc:
            logger.exception("FFmpeg timed out while extracting audio")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Audio extraction timed out.",
            ) from exc

        if not output_path.exists() or output_path.stat().st_size == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Extracted audio is empty.",
            )

        return output_path

    def _validate_media_file(self, source_path: Path, file_extension: str) -> None:
        """Validate that the stored media file exists and has a supported extension."""
        if file_extension not in ALLOWED_FILE_EXTENSIONS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unsupported file type.",
            )

        if not source_path.exists() or not source_path.is_file():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Uploaded meeting file was not found.",
            )

        if source_path.stat().st_size == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded meeting file is empty.",
            )

    def _validate_duration(self, duration_seconds: int | None) -> None:
        """Validate media duration when FFprobe can determine it."""
        if duration_seconds is None:
            return

        if duration_seconds > settings.MAX_AUDIO_DURATION_SECONDS:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="Meeting duration exceeds the maximum supported length.",
            )
