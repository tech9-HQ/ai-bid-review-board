"""
app/core/exceptions.py
───────────────────────
Custom exception hierarchy and FastAPI exception handlers.
"""
from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from loguru import logger


# ── Base Exception ────────────────────────────────────────────────────────

class BidReviewError(Exception):
    """Base exception for all bid review errors."""

    def __init__(self, message: str, detail: str | None = None):
        super().__init__(message)
        self.detail = detail


# ── Pipeline & AI Errors ─────────────────────────────────────────────────

class PipelineError(BidReviewError):
    """Raised when a pipeline stage fails unrecoverably."""
    pass


class AIProviderError(BidReviewError):
    """Raised on Claude / Bedrock API failures."""
    pass


# ── File & Parsing Errors ────────────────────────────────────────────────

class FileTooLargeError(BidReviewError):
    """Raised when an uploaded file exceeds the size limit."""
    pass


class UnsupportedFileTypeError(BidReviewError):
    """Raised when an uploaded file has an unsupported extension."""
    pass


class DocumentParseError(BidReviewError):
    """Raised when document parsing fails."""
    pass


# ── Session Errors ───────────────────────────────────────────────────────

class SessionNotFoundError(BidReviewError):
    """Raised when a session ID cannot be found."""
    pass


# ── Output Errors ────────────────────────────────────────────────────────

class OutputGenerationError(BidReviewError):
    """Raised when document generation fails."""
    pass


# ── Exception Handlers ───────────────────────────────────────────────────

def register_exception_handlers(app: FastAPI) -> None:
    """Register all custom exception handlers on the FastAPI app."""

    @app.exception_handler(PipelineError)
    async def pipeline_error_handler(request: Request, exc: PipelineError) -> JSONResponse:
        logger.error(f"Pipeline error on {request.url}: {exc}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": "pipeline_error", "detail": str(exc)},
        )

    @app.exception_handler(AIProviderError)
    async def ai_provider_error_handler(request: Request, exc: AIProviderError) -> JSONResponse:
        logger.error(f"AI provider error on {request.url}: {exc}")
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={
                "error": "ai_provider_error",
                "detail": str(exc),
                "provider": "AWS Bedrock (Claude)",
            },
        )

    @app.exception_handler(FileTooLargeError)
    async def file_too_large_handler(request: Request, exc: FileTooLargeError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            content={"error": "file_too_large", "detail": str(exc)},
        )

    @app.exception_handler(UnsupportedFileTypeError)
    async def unsupported_file_type_handler(request: Request, exc: UnsupportedFileTypeError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            content={"error": "unsupported_file_type", "detail": str(exc)},
        )

    @app.exception_handler(DocumentParseError)
    async def document_parse_handler(request: Request, exc: DocumentParseError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "document_parse_error", "detail": str(exc)},
        )

    @app.exception_handler(SessionNotFoundError)
    async def session_not_found_handler(request: Request, exc: SessionNotFoundError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"error": "session_not_found", "detail": str(exc)},
        )

    @app.exception_handler(OutputGenerationError)
    async def output_generation_handler(request: Request, exc: OutputGenerationError) -> JSONResponse:
        logger.error(f"Output generation error on {request.url}: {exc}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": "output_generation_error", "detail": str(exc)},
        )

    @app.exception_handler(Exception)
    async def generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(f"Unhandled exception on {request.url}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "internal_error",
                "detail": "An unexpected error occurred. Please try again.",
            },
        )