"""
main.py
────────
FastAPI application factory.

Run with:
    uvicorn main:app --reload                    # development
    uvicorn main:app --host 0.0.0.0 --port 8000  # production
"""
from __future__ import annotations

import sentry_sdk
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from loguru import logger

from app.api.routes import router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import setup_logging


def create_app() -> FastAPI:
    """Application factory."""

    # ── Logging ────────────────────────────────────────────────────────────────
    setup_logging()

    # ── Sentry (production error tracking) ────────────────────────────────────
    if settings.SENTRY_DSN:
        sentry_sdk.init(
            dsn=settings.SENTRY_DSN,
            environment=settings.APP_ENV,
            traces_sample_rate=0.2,
        )
        logger.info("Sentry error tracking enabled")

    # ── FastAPI App ────────────────────────────────────────────────────────────
    app = FastAPI(
        title="Tech9Labs AI Bid Review Board",
        description=(
            "Mandatory pre-submission gate for all Tech9Labs / Tech9IQ proposals. "
            "Powered by OpenAI GPT-4o (audit + rewrite) and Anthropic Claude (legal review)."
        ),
        version=settings.APP_VERSION,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # ── Middleware ─────────────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    # ── Exception Handlers ─────────────────────────────────────────────────────
    register_exception_handlers(app)

    # ── Routes ─────────────────────────────────────────────────────────────────
    app.include_router(router)

    # ── Startup ────────────────────────────────────────────────────────────────
    @app.on_event("startup")
    async def startup_event() -> None:
        settings.ensure_dirs()
        logger.info(
            f"Tech9Labs AI Bid Review Board v{settings.APP_VERSION} started "
            f"[env={settings.APP_ENV}]"
        )

    logger.info("Application factory complete")
    return app


app = create_app()