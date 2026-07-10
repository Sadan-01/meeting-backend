"""Production middleware for request context, logging, and security headers."""

import logging
import time
from collections.abc import Callable
from uuid import uuid4

from fastapi import Request, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.core.config import settings
from app.core.responses import error_response

logger = logging.getLogger(__name__)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Add request ids, request logging, timing, and security headers."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process a request and attach observability metadata."""
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        request.state.request_id = request_id
        started_at = time.perf_counter()

        content_length = request.headers.get("content-length")
        if content_length and _exceeds_max_request_size(content_length):
            response = error_response(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                message="Request payload is too large.",
                code="PAYLOAD_TOO_LARGE",
                details={"request_id": request_id},
            )
            _attach_response_headers(response, request_id, started_at)
            _log_request(request, response.status_code, started_at, request_id)
            return response

        try:
            response = await call_next(request)
        except Exception:
            _log_request(request, status.HTTP_500_INTERNAL_SERVER_ERROR, started_at, request_id)
            raise

        _attach_response_headers(response, request_id, started_at)
        _log_request(request, response.status_code, started_at, request_id)
        return response


def parse_csv_setting(value: str) -> list[str]:
    """Parse comma-separated settings while preserving wildcard support."""
    items = [item.strip() for item in value.split(",") if item.strip()]
    return items or ["*"]


def _exceeds_max_request_size(content_length: str) -> bool:
    """Return whether the request content length exceeds the configured limit."""
    try:
        return int(content_length) > settings.MAX_REQUEST_SIZE
    except ValueError:
        return False


def _attach_response_headers(response: Response, request_id: str, started_at: float) -> None:
    """Attach request id, timing, and security headers to a response."""
    duration_ms = (time.perf_counter() - started_at) * 1000
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Process-Time"] = f"{duration_ms:.2f}ms"

    if not settings.SECURITY_HEADERS:
        return

    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")


def _log_request(request: Request, status_code: int, started_at: float, request_id: str) -> None:
    """Write a structured, sanitized request log entry."""
    duration_ms = (time.perf_counter() - started_at) * 1000
    client_host = request.client.host if request.client else "unknown"
    logger.info(
        "request completed request_id=%s method=%s path=%s status_code=%s duration_ms=%.2f client=%s",
        request_id,
        request.method,
        request.url.path,
        status_code,
        duration_ms,
        client_host,
    )
