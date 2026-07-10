"""Health and readiness checks for deployment monitoring."""

from datetime import UTC, datetime
import os
from pathlib import Path
from typing import Any

from sqlalchemy import text

from app.core.config import settings
from app.database.database import SessionLocal
from app.utils.upload import resolve_upload_root

APP_STARTED_AT = datetime.now(UTC)


def build_health_report() -> dict[str, Any]:
    """Return a complete health report without exposing secrets."""
    database = check_database()
    upload_directory = check_upload_directory()
    server_time = datetime.now(UTC)
    status = "healthy" if database["status"] == "healthy" and upload_directory["status"] == "healthy" else "degraded"

    return {
        "status": status,
        "application": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT,
        "server_time": server_time.isoformat(),
        "uptime_seconds": int((server_time - APP_STARTED_AT).total_seconds()),
        "checks": {
            "database": database,
            "openai": {
                "status": "configured" if bool(settings.OPENAI_API_KEY) else "not_configured",
                "transcription_model": settings.OPENAI_TRANSCRIPTION_MODEL,
                "analysis_model": settings.OPENAI_ANALYSIS_MODEL,
            },
            "upload_directory": upload_directory,
        },
    }


def build_readiness_report() -> tuple[dict[str, Any], int]:
    """Return readiness report and HTTP status code."""
    health = build_health_report()
    ready = health["checks"]["database"]["status"] == "healthy" and health["checks"]["upload_directory"]["status"] == "healthy"
    status_code = 200 if ready else 503
    return {"ready": ready, **health}, status_code


def check_database() -> dict[str, Any]:
    """Validate that the database accepts a simple query."""
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        return {"status": "healthy"}
    except Exception:
        return {"status": "unhealthy"}


def check_upload_directory() -> dict[str, Any]:
    """Validate that the upload directory exists and is writable."""
    try:
        upload_root = resolve_upload_root()
        upload_root.mkdir(parents=True, exist_ok=True)
        is_ready = upload_root.is_dir() and os.access(upload_root, os.W_OK)
        return {"status": "healthy" if is_ready else "unhealthy", "configured": True}
    except Exception:
        return {"status": "unhealthy", "configured": bool(Path(settings.UPLOAD_DIRECTORY))}
