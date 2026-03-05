"""
app/core/logging.py
────────────────────
Loguru-based structured logger.
Every service imports `logger` from here.
"""
import sys
from loguru import logger
from app.core.config import settings


def setup_logging() -> None:
    logger.remove()  # Remove default handler

    fmt = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "<level>{message}</level>"
    )

    if settings.APP_ENV == "production":
        # JSON lines for log aggregators (Datadog, CloudWatch, etc.)
        logger.add(
            sys.stdout,
            format="{message}",
            level="INFO",
            serialize=True,
        )
    else:
        logger.add(sys.stdout, format=fmt, level="DEBUG", colorize=True)
        logger.add(
            "logs/app.log",
            format=fmt,
            level="DEBUG",
            rotation="10 MB",
            retention="7 days",
            compression="zip",
        )