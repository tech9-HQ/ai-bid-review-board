"""
main.py
────────
FastAPI application factory — Claude-only edition.

Run with:
  uvicorn main:app --reload                        # development
  gunicorn main:app -w 2 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000  # production
"""
from __future__ import annotations

from contextlib import asynccontextmanager

import sentry_sdk
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from loguru import logger
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.api.routes import router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown logic using the modern lifespan pattern."""
    # ── Startup ─────────────────────────────────────────────────────────
    settings.ensure_dirs()
    logger.info(
        f"Tech9Labs AI Bid Review Board v{settings.APP_VERSION} started "
        f"[env={settings.APP_ENV}] "
        f"[fast_model={settings.CLAUDE_FAST_MODEL}] "
        f"[legal_model={settings.CLAUDE_LEGAL_MODEL}]"
    )
    yield
    # ── Shutdown ─────────────────────────────────────────────────────────
    logger.info("Application shutting down")


def create_app() -> FastAPI:
    """Application factory."""

    # ── Logging ────────────────────────────────────────────────────────────
    setup_logging()

    # ── Sentry ─────────────────────────────────────────────────────────────
    if settings.SENTRY_DSN:
        sentry_sdk.init(
            dsn=settings.SENTRY_DSN,
            environment=settings.APP_ENV,
            traces_sample_rate=0.2,
        )
        logger.info("Sentry error tracking enabled")

    # ── Rate Limiter ───────────────────────────────────────────────────────
    limiter = Limiter(key_func=get_remote_address)

    # ── FastAPI App ────────────────────────────────────────────────────────
    app = FastAPI(
        title=settings.APP_TITLE,
        description=(
            "Mandatory pre-submission governance gate for all proposals. "
            "Powered exclusively by Anthropic Claude (Sonnet for speed, Opus for legal precision)."
        ),
        version=settings.APP_VERSION,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # ── Middleware ─────────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    # ── Rate Limit State & Handler ─────────────────────────────────────────
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # ── Custom Exception Handlers ──────────────────────────────────────────
    register_exception_handlers(app)

    # ── Routes ─────────────────────────────────────────────────────────────
    app.include_router(router)

    logger.info("Application factory complete")
    return app


app = create_app()