"""Database enum definitions."""

from enum import StrEnum


class ProcessingStatus(StrEnum):
    """Supported meeting processing states."""

    UPLOADED = "UPLOADED"
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    TRANSCRIBED = "TRANSCRIBED"
    ANALYZING = "ANALYZING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
