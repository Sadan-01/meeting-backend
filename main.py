"""FastAPI application entry point for MeetMind AI."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.auth import router as auth_router
from app.api.dashboard import router as dashboard_router
from app.api.meetings import router as meetings_router
from app.api.root import router as root_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware, parse_csv_setting
from app.database.database import init_db

configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Handle application startup and shutdown tasks."""
    try:
        init_db()
        logger.info("%s server startup complete", settings.PROJECT_NAME)
        yield
    except Exception:
        logger.exception("Application startup failed")
        raise
    finally:
        logger.info("%s server shutdown complete", settings.PROJECT_NAME)


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Production backend API for MeetMind AI meeting upload, processing, analysis, chat, exports, and dashboard workflows.",
    debug=settings.ENABLE_DEBUG,
    docs_url="/docs" if settings.ENABLE_DOCS else None,
    redoc_url="/redoc" if settings.ENABLE_DOCS else None,
    openapi_url="/openapi.json" if settings.ENABLE_DOCS else None,
    lifespan=lifespan,
)

trusted_hosts = parse_csv_setting(settings.TRUSTED_HOSTS)
if trusted_hosts != ["*"]:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=trusted_hosts)

app.add_middleware(
    CORSMiddleware,
    allow_origins=parse_csv_setting(settings.ALLOWED_ORIGINS),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestContextMiddleware)

app.include_router(root_router)
app.include_router(auth_router)
app.include_router(meetings_router)
app.include_router(dashboard_router)

register_exception_handlers(app)
