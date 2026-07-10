"""Centralized exception handlers for production-safe API errors."""

import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.core.responses import error_response

try:  # pragma: no cover - dependency is declared for AI modules.
    from openai import APIConnectionError, APIError, APITimeoutError, RateLimitError
except ImportError:  # pragma: no cover
    APIConnectionError = APIError = APITimeoutError = RateLimitError = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

HTTP_ERROR_CODES = {
    status.HTTP_400_BAD_REQUEST: "BAD_REQUEST",
    status.HTTP_401_UNAUTHORIZED: "UNAUTHORIZED",
    status.HTTP_403_FORBIDDEN: "FORBIDDEN",
    status.HTTP_404_NOT_FOUND: "NOT_FOUND",
    status.HTTP_409_CONFLICT: "CONFLICT",
    status.HTTP_413_REQUEST_ENTITY_TOO_LARGE: "PAYLOAD_TOO_LARGE",
    status.HTTP_422_UNPROCESSABLE_ENTITY: "VALIDATION_ERROR",
    status.HTTP_429_TOO_MANY_REQUESTS: "RATE_LIMITED",
    status.HTTP_500_INTERNAL_SERVER_ERROR: "INTERNAL_SERVER_ERROR",
    status.HTTP_503_SERVICE_UNAVAILABLE: "SERVICE_UNAVAILABLE",
    status.HTTP_504_GATEWAY_TIMEOUT: "GATEWAY_TIMEOUT",
}


def register_exception_handlers(app: FastAPI) -> None:
    """Register all centralized exception handlers on the FastAPI app."""
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, request_validation_exception_handler)
    app.add_exception_handler(ValidationError, pydantic_validation_exception_handler)
    app.add_exception_handler(SQLAlchemyError, sqlalchemy_exception_handler)
    app.add_exception_handler(OSError, file_system_exception_handler)
    if APIError is not None:
        app.add_exception_handler(APIError, openai_exception_handler)
    if APIConnectionError is not None:
        app.add_exception_handler(APIConnectionError, openai_exception_handler)
    if APITimeoutError is not None:
        app.add_exception_handler(APITimeoutError, openai_exception_handler)
    if RateLimitError is not None:
        app.add_exception_handler(RateLimitError, openai_exception_handler)
    app.add_exception_handler(Exception, unexpected_exception_handler)


async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle intentionally raised HTTP exceptions."""
    message = _safe_message(exc.detail, fallback="Request failed.")
    code = HTTP_ERROR_CODES.get(exc.status_code, f"HTTP_{exc.status_code}")
    if exc.status_code >= 500:
        logger.warning(
            "Handled HTTP error request_id=%s method=%s path=%s status_code=%s",
            _request_id(request),
            request.method,
            request.url.path,
            exc.status_code,
        )
    return error_response(
        status_code=exc.status_code,
        message=message,
        code=code,
        details=_request_details(request),
        headers=exc.headers,
    )


async def request_validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle FastAPI request validation failures without echoing sensitive input."""
    errors = _sanitize_validation_errors(exc.errors())
    message = errors[0]["message"] if errors else "Invalid request payload."
    logger.info(
        "Request validation failed request_id=%s method=%s path=%s",
        _request_id(request),
        request.method,
        request.url.path,
    )
    return error_response(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        message=message,
        code="VALIDATION_ERROR",
        details={**_request_details(request), "errors": errors},
    )


async def pydantic_validation_exception_handler(request: Request, exc: ValidationError):
    """Handle application-level Pydantic validation failures."""
    errors = _sanitize_validation_errors(exc.errors())
    logger.warning(
        "Application validation failed request_id=%s method=%s path=%s",
        _request_id(request),
        request.method,
        request.url.path,
    )
    return error_response(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        message="Validation failed.",
        code="VALIDATION_ERROR",
        details={**_request_details(request), "errors": errors},
    )


async def sqlalchemy_exception_handler(request: Request, exc: SQLAlchemyError):
    """Handle database failures without exposing SQL or connection details."""
    logger.exception(
        "Database error request_id=%s method=%s path=%s",
        _request_id(request),
        request.method,
        request.url.path,
    )
    return error_response(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        message="A database error occurred.",
        code="DATABASE_ERROR",
        details=_request_details(request),
    )


async def openai_exception_handler(request: Request, exc: Exception):
    """Handle OpenAI SDK failures with sanitized client-facing messages."""
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "OPENAI_API_ERROR"
    message = "AI service is temporarily unavailable."

    if RateLimitError is not None and isinstance(exc, RateLimitError):
        status_code = status.HTTP_429_TOO_MANY_REQUESTS
        code = "OPENAI_RATE_LIMITED"
    elif APITimeoutError is not None and isinstance(exc, APITimeoutError):
        status_code = status.HTTP_504_GATEWAY_TIMEOUT
        code = "OPENAI_TIMEOUT"
        message = "AI service request timed out."
    elif APIConnectionError is not None and isinstance(exc, APIConnectionError):
        code = "OPENAI_CONNECTION_ERROR"

    logger.exception(
        "OpenAI error request_id=%s method=%s path=%s code=%s",
        _request_id(request),
        request.method,
        request.url.path,
        code,
    )
    return error_response(
        status_code=status_code,
        message=message,
        code=code,
        details=_request_details(request),
    )


async def file_system_exception_handler(request: Request, exc: OSError):
    """Handle file system failures without exposing server paths."""
    logger.exception(
        "File system error request_id=%s method=%s path=%s",
        _request_id(request),
        request.method,
        request.url.path,
    )
    return error_response(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        message="A file storage error occurred.",
        code="FILE_SYSTEM_ERROR",
        details=_request_details(request),
    )


async def unexpected_exception_handler(request: Request, exc: Exception):
    """Handle uncaught exceptions with a generic production-safe response."""
    logger.exception(
        "Unhandled exception request_id=%s method=%s path=%s",
        _request_id(request),
        request.method,
        request.url.path,
    )
    return error_response(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        message="Internal server error.",
        code="INTERNAL_SERVER_ERROR",
        details=_request_details(request),
    )


def _safe_message(detail: Any, *, fallback: str) -> str:
    """Convert exception detail into a non-sensitive message string."""
    if isinstance(detail, str) and detail:
        return detail
    if isinstance(detail, dict):
        message = detail.get("message") or detail.get("detail")
        if isinstance(message, str) and message:
            return message
    return fallback


def _sanitize_validation_errors(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove raw input values from validation details."""
    sanitized: list[dict[str, Any]] = []
    for error in errors:
        sanitized.append(
            {
                "field": ".".join(str(part) for part in error.get("loc", [])),
                "message": str(error.get("msg", "Invalid value.")),
                "type": str(error.get("type", "validation_error")),
            }
        )
    return sanitized


def _request_id(request: Request) -> str | None:
    """Return the request id assigned by middleware, if available."""
    value = getattr(request.state, "request_id", None)
    return str(value) if value else None


def _request_details(request: Request) -> dict[str, Any]:
    """Return safe per-request diagnostic details."""
    request_id = _request_id(request)
    return {"request_id": request_id} if request_id else {}
