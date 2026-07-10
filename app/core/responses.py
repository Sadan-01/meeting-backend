"""Shared response helpers for API error handling."""

from typing import Any

from fastapi.responses import JSONResponse


def build_error_payload(
    *,
    message: str,
    code: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the standard API failure envelope."""
    return {
        "success": False,
        "message": message,
        "error": {
            "code": code,
            "details": details or {},
        },
    }


def error_response(
    *,
    status_code: int,
    message: str,
    code: str,
    details: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Return a JSON error response using the standard envelope."""
    return JSONResponse(
        status_code=status_code,
        content=build_error_payload(message=message, code=code, details=details),
        headers=headers,
    )
