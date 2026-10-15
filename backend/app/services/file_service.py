"""
Upload validation: extension, size, filename length and magic bytes.
"""

import os

from app.config import settings

SUPPORTED_EXTS = {".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp"}

# Magic bytes for content-type validation
_MAGIC_BYTES = {
    ".pdf": b"%PDF-",
    ".png": b"\x89PNG\r\n\x1a\n",
    ".jpg": b"\xff\xd8\xff",
    ".jpeg": b"\xff\xd8\xff",
    ".tiff": (b"II\x2a\x00", b"MM\x00\x2a"),  # little-endian, big-endian
    ".tif": (b"II\x2a\x00", b"MM\x00\x2a"),
    ".bmp": b"BM",
}

MAX_FILENAME_LENGTH = 255
PDF_MAGIC = b"%PDF-"
PDF_MIN_HEADER = 5


def validate_file(
    filename: str,
    file_size: int,
    content: bytes | None = None,
    *,
    pdf_only: bool = False,
) -> tuple[bool, str]:
    """Validate file extension, size, filename length, and magic bytes.
    Magic-byte check is mandatory whenever ``content`` is supplied. Set
    ``pdf_only=True`` to reject everything but PDFs (server-side enforcement
    that survives any client bypass). Returns (ok, error_message)."""
    if not filename or len(filename) > MAX_FILENAME_LENGTH:
        return False, f"Filename must be between 1 and {MAX_FILENAME_LENGTH} characters"

    ext = os.path.splitext(filename)[1].lower()
    allowed = {".pdf"} if pdf_only else SUPPORTED_EXTS
    if ext not in allowed:
        return False, "Only PDF files are accepted" if pdf_only else f"Unsupported file type: {ext}"

    max_bytes = settings.max_file_size_mb * 1024 * 1024
    if file_size > max_bytes:
        return False, f"File exceeds {settings.max_file_size_mb}MB limit"

    if pdf_only:
        # PDF magic bytes are mandatory — never trust the extension alone.
        if not content or len(content) < PDF_MIN_HEADER:
            return False, "Cannot verify PDF signature: file header missing"
        if not content.startswith(PDF_MAGIC):
            return False, "File content does not match PDF format (magic-byte check failed)"
        return True, ""

    # Magic byte validation for the broader allowed set
    if content and len(content) >= 4:
        expected = _MAGIC_BYTES.get(ext)
        if expected is not None:
            if isinstance(expected, tuple):
                # Multiple valid signatures (e.g., TIFF)
                if not any(content.startswith(sig) for sig in expected):
                    return False, f"File content does not match expected {ext} format"
            else:
                if not content.startswith(expected):
                    return False, f"File content does not match expected {ext} format"

    return True, ""
