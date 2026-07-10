"""Reusable helpers for secure meeting upload handling."""

import re
import shutil
import stat
import time
import gc
from pathlib import Path, PurePath
from uuid import uuid4

from fastapi import HTTPException, UploadFile, status

from app.core.config import BASE_DIR, settings

ALLOWED_FILE_EXTENSIONS = frozenset({".mp3", ".wav", ".mp4", ".m4a"})
ALLOWED_CONTENT_TYPES = frozenset(
    {
        "audio/mpeg",
        "audio/mp3",
        "audio/wav",
        "audio/wave",
        "audio/x-wav",
        "video/mp4",
        "audio/mp4",
        "audio/x-m4a",
    }
)
CHUNK_SIZE_BYTES = 1024 * 1024
MAX_FILENAME_LENGTH = 255
SAFE_FILENAME_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")


def resolve_upload_root() -> Path:
    """Return the absolute upload root directory."""
    upload_directory = Path(settings.UPLOAD_DIRECTORY)
    if upload_directory.is_absolute():
        return upload_directory
    return BASE_DIR / upload_directory


def get_file_extension(filename: str | None) -> str:
    """Return the lowercase file extension from an uploaded filename."""
    if not filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid filename.",
        )

    extension = PurePath(filename).suffix.lower()
    if not extension:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file must include a file extension.",
        )
    return extension


def sanitize_uploaded_filename(filename: str | None) -> str:
    """Return a safe display filename derived from the uploaded filename."""
    if not filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid filename.",
        )

    safe_name = PurePath(filename).name.strip()
    safe_name = SAFE_FILENAME_PATTERN.sub("_", safe_name)
    safe_name = safe_name.strip("._ ")

    if not safe_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid filename.",
        )

    if len(safe_name) > MAX_FILENAME_LENGTH:
        extension = Path(safe_name).suffix
        stem_limit = MAX_FILENAME_LENGTH - len(extension)
        safe_name = f"{Path(safe_name).stem[:stem_limit]}{extension}"

    return safe_name


def validate_file(file: UploadFile) -> str:
    """Validate the uploaded file metadata and return its extension."""
    extension = get_file_extension(file.filename)
    if extension not in ALLOWED_FILE_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported file type.",
        )

    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported file content type.",
        )

    return extension


def generate_safe_filename(file_extension: str) -> tuple[str, str]:
    """Generate a UUID directory name and UUID-based stored filename."""
    meeting_uuid = str(uuid4())
    stored_filename = f"{meeting_uuid}{file_extension}"
    return meeting_uuid, stored_filename


def create_upload_directory(user_id: int, meeting_uuid: str) -> Path:
    """Create and return the per-user, per-meeting upload directory."""
    upload_directory = resolve_upload_root() / f"user_{user_id}" / meeting_uuid
    upload_directory.mkdir(parents=True, exist_ok=False)
    return upload_directory


def get_meeting_directory(user_id: int, stored_filename: str) -> Path:
    """Resolve the upload directory for a stored meeting file."""
    meeting_uuid = Path(stored_filename).stem
    return resolve_upload_root() / f"user_{user_id}" / meeting_uuid


def get_meeting_file_path(user_id: int, stored_filename: str) -> Path:
    """Resolve and validate the stored meeting file path."""
    meeting_directory = get_meeting_directory(user_id, stored_filename)
    file_path = meeting_directory / Path(stored_filename).name
    upload_root = resolve_upload_root().resolve()
    resolved_file_path = file_path.resolve()

    if upload_root not in resolved_file_path.parents:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid meeting storage path.",
        )

    return resolved_file_path


def delete_meeting_directory(user_id: int, stored_filename: str) -> None:
    """Delete the per-meeting upload directory if it exists."""
    meeting_directory = get_meeting_directory(user_id, stored_filename)
    upload_root = resolve_upload_root().resolve()
    resolved_directory = meeting_directory.resolve()

    if upload_root not in resolved_directory.parents:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid meeting storage path.",
        )

    if resolved_directory.exists():
        gc.collect()
        for attempt in range(40):
            try:
                shutil.rmtree(resolved_directory, onerror=_handle_remove_readonly)
                return
            except PermissionError:
                if attempt == 39:
                    raise
                time.sleep(0.25)


def format_file_size(size_bytes: int) -> str:
    """Return a human-readable file size string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024**2:
        return f"{size_bytes / 1024:.2f} KB"
    if size_bytes < 1024**3:
        return f"{size_bytes / 1024**2:.2f} MB"
    return f"{size_bytes / 1024**3:.2f} GB"


def _handle_remove_readonly(function: object, path: str, exc_info: object) -> None:
    """Make a readonly file writable and retry deletion."""
    target = Path(path)
    target.chmod(stat.S_IWRITE)
    function(path)
