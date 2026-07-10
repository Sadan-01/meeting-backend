"""Root and health-check API endpoints."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.health import build_health_report, build_readiness_report

router = APIRouter(tags=["System"])


@router.get("/")
def read_root() -> dict[str, str]:
    """Return a basic service availability message."""
    return {"message": "MeetMind AI Backend Running"}


@router.get(
    "/health",
    summary="Application health check",
    description="Return application, database, OpenAI configuration, upload storage, version, environment, server time, and uptime status.",
)
def health_check() -> dict[str, object]:
    """Return the current application health report."""
    return build_health_report()


@router.get(
    "/ready",
    summary="Application readiness check",
    description="Return whether the application is ready to accept traffic.",
)
def readiness_check() -> JSONResponse:
    """Return readiness information for load balancers and deployment platforms."""
    report, status_code = build_readiness_report()
    return JSONResponse(status_code=status_code, content=report)
