"""
app/utils/file_utils.py
────────────────────────
File validation helpers used by the API layer.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import UploadFile

from app.core.config import settings
from app.core.exceptions import FileTooLargeError, UnsupportedFileTypeError

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".xls", ".txt", ".csv"}

# Role names expected in a full deal submission
REQUIRED_DOCUMENT_ROLES = {"crm", "requirements", "sizing", "boq", "proposal"}
OPTIONAL_DOCUMENT_ROLES = {"commercial", "sow", "tnc"}
ALL_ROLES = REQUIRED_DOCUMENT_ROLES | OPTIONAL_DOCUMENT_ROLES


async def read_upload_file(upload: UploadFile) -> tuple[bytes, str]:
    """
    Read an UploadFile into memory, validating size and extension.

    Returns:
        (file_bytes, original_filename)

    Raises:
        FileTooLargeError: If file exceeds MAX_UPLOAD_SIZE_MB.
        UnsupportedFileTypeError: If extension is not allowed.
    """
    filename = upload.filename or "unknown"
    ext = Path(filename).suffix.lower()

    if ext not in ALLOWED_EXTENSIONS:
        raise UnsupportedFileTypeError(
            f"File '{filename}' has unsupported type '{ext}'.",
            detail=f"Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    content = await upload.read()

    if len(content) > settings.max_upload_bytes:
        raise FileTooLargeError(
            f"File '{filename}' exceeds {settings.MAX_UPLOAD_SIZE_MB}MB limit.",
            detail=f"File size: {len(content) / 1024 / 1024:.1f}MB",
        )

    return content, filename


def sanitise_deal_name(name: str) -> str:
    """Strip unsafe characters from deal names used in file paths."""
    import re
    safe = re.sub(r"[^\w\s\-]", "", name).strip()
    return safe[:100] or "unnamed_deal"