"""Logging configuration for the MeetMind AI backend."""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.core.config import BASE_DIR, settings

upload_directory = Path(settings.UPLOAD_DIRECTORY)
if not upload_directory.is_absolute():
    upload_directory = BASE_DIR / upload_directory

LOG_DIRECTORY = upload_directory.parent / "logs"
LOG_FILE = LOG_DIRECTORY / "app.log"


def configure_logging() -> None:
    """Configure console and rotating file logging for the application."""
    LOG_DIRECTORY.mkdir(parents=True, exist_ok=True)

    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    log_format = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.handlers.clear()

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(logging.Formatter(log_format))

    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=5_242_880,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(logging.Formatter(log_format))

    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
