"""
app/core/exceptions.py
───────────────────────
Custom exceptions + FastAPI exception handlers.
All API errors return a consistent JSON envelope.
"""
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from loguru import logger


# ── Exception Hierarchy ───────────────────────────────────────────────────────

class BidReviewError(Exception):
    """Base exception for all Bid Review Board errors."""
    status_code: int = 500
    error_code: str = "INTERNAL_ERROR"

    def __init__(self, message: str, detail: str | None = None):
        self.message = message
        self.detail = detail
        super().__init__(message)


class DocumentParseError(BidReviewError):
    status_code = 422
    error_code = "DOCUMENT_PARSE_ERROR"


class UnsupportedFileTypeError(BidReviewError):
    status_code = 415
    error_code = "UNSUPPORTED_FILE_TYPE"


class FileTooLargeError(BidReviewError):
    status_code = 413
    error_code = "FILE_TOO_LARGE"


class AIProviderError(BidReviewError):
    status_code = 502
    error_code = "AI_PROVIDER_ERROR"


class AIResponseParseError(BidReviewError):
    status_code = 502
    error_code = "AI_RESPONSE_PARSE_ERROR"


class MissingRequiredDocumentError(BidReviewError):
    status_code = 400
    error_code = "MISSING_REQUIRED_DOCUMENT"


class OutputGenerationError(BidReviewError):
    status_code = 500
    error_code = "OUTPUT_GENERATION_ERROR"


# ── FastAPI Exception Handlers ────────────────────────────────────────────────

def _error_envelope(request: Request, exc: BidReviewError) -> JSONResponse:
    logger.error(
        f"[{exc.error_code}] {exc.message}",
        detail=exc.detail,
        path=str(request.url),
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error": {
                "code": exc.error_code,
                "message": exc.message,
                "detail": exc.detail,
            },
        },
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(BidReviewError)
    async def bid_review_handler(request: Request, exc: BidReviewError):
        return _error_envelope(request, exc)

    @app.exception_handler(Exception)
    async def generic_handler(request: Request, exc: Exception):
        logger.exception(f"Unhandled exception at {request.url}: {exc}")
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "An unexpected error occurred.",
                    "detail": str(exc) if True else None,
                },
            },
        )