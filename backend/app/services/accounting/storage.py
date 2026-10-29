"""Upload storage for AutoAccounting: stream files to the long-retention root."""

import asyncio
import hashlib
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile

from PIL import Image, UnidentifiedImageError

from app.config import settings
from app.services.accounting.compress import PDF_POOL, compress_file
from app.services.accounting.page_trim import render_pdf_page_trimmed, trimmed_image
from app.services.file_service import validate_file
from app.services.gemini_service import get_pdf_page_count_safe, render_pdf_page_webp

ALLOWED_EXTS = {".pdf": "pdf", ".png": "png", ".jpg": "jpg", ".jpeg": "jpg"}
_CHUNK = 1024 * 1024


class UploadRejected(ValueError):
    """A file the user must be told about by name (bad type, empty, unreadable)."""


@dataclass(frozen=True)
class StoredUpload:
    filename: str
    stored_path: str
    size: int
    sha256: str
    file_type: str
    page_count: int


# Phone cameras top out well below this; larger "images" are decompression bombs.
MAX_IMAGE_PIXELS = 60_000_000


def _image_problem(path: Path) -> str | None:
    """None if the image decodes fully; else "too_large" or "unreadable".

    Dimensions are read from the header first, so an oversized image is rejected
    without ever being decoded.
    """
    try:
        with Image.open(path) as img:
            width, height = img.size
            if width * height > MAX_IMAGE_PIXELS:
                return "too_large"
            img.load()
        return None
    except Image.DecompressionBombError:
        return "too_large"
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
        return "unreadable"


def upload_dir(upload_id: uuid.UUID) -> Path:
    return Path(settings.accounting_root) / "accounting" / str(upload_id)


async def stream_upload(f: UploadFile, dest_dir: Path) -> StoredUpload:
    """Write one upload under ``dest_dir``; validate type, size, magic bytes and readability."""
    filename = (f.filename or "unknown")[:255]
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTS:
        raise UploadRejected(f"'{filename}': only PDF, PNG and JPG files are accepted")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{uuid.uuid4()}{ext}"
    max_bytes = settings.max_file_size_mb * 1024 * 1024
    digest = hashlib.sha256()
    total = 0
    header = b""
    try:
        with open(dest, "wb") as out:
            while chunk := await f.read(_CHUNK):
                total += len(chunk)
                if total > max_bytes:
                    raise UploadRejected(f"'{filename}' exceeds the {settings.max_file_size_mb}MB limit")
                if len(header) < 16:
                    header += chunk[: 16 - len(header)]
                digest.update(chunk)
                out.write(chunk)
        if total == 0:
            raise UploadRejected(f"'{filename}' is empty")
        ok, err = validate_file(filename, total, header)
        if not ok:
            raise UploadRejected(f"'{filename}': {err}")
        file_type = ALLOWED_EXTS[ext]
        page_count = 1
        loop = asyncio.get_running_loop()  # parsing/decoding is CPU work: keep it off the event loop
        if file_type == "pdf":
            page_count = await loop.run_in_executor(None, get_pdf_page_count_safe, str(dest))
            if page_count < 1:
                raise UploadRejected(f"'{filename}' couldn't be opened as a PDF")
        else:
            problem = await loop.run_in_executor(None, _image_problem, dest)
            if problem == "too_large":
                raise UploadRejected(f"'{filename}' is too large an image (over {MAX_IMAGE_PIXELS // 1_000_000} megapixels)")
            if problem:
                raise UploadRejected(f"'{filename}' couldn't be opened as an image")
    except UploadRejected:
        dest.unlink(missing_ok=True)
        raise
    # Keep a smaller copy (same pages, ~200 dpi). The hash stays the original's so re-drops are still duplicates.
    # PDFs wait their turn on the single rewrite worker (see compress.PDF_POOL) rather than being skipped.
    kept = await loop.run_in_executor(PDF_POOL if file_type == "pdf" else None, compress_file, str(dest), file_type)
    return StoredUpload(filename, kept.path, kept.size, digest.hexdigest(), kept.file_type, page_count)


def is_stored_path_safe(stored_path: str, root: str | None = None) -> bool:
    """True when ``stored_path`` resolves inside the accounting root (defence in depth)."""
    base = Path(root or settings.accounting_root).resolve()
    return Path(stored_path).resolve().is_relative_to(base)


def counts_as_filed(file_status: str, live_document_count: int) -> bool:
    """Whether an earlier file with the same hash makes a new drop a duplicate.

    Only files that actually produced documents still on record count; files
    from unfinished, failed or skipped uploads (or whose documents were all
    deleted) may be dropped again.
    """
    return file_status == "extracted" and live_document_count > 0


def filed_hashes(rows, company_id) -> set[str]:
    """Hashes already filed for ``company_id``.

    ``rows`` are ``(sha256, company_id, file_status, live_document_count)``.
    Dedupe is per company: the same invoice may legitimately be filed for both
    parties when the firm keeps books for each of them.
    """
    return {
        sha for sha, cid, file_status, doc_count in rows
        if str(cid) == str(company_id) and counts_as_filed(file_status, doc_count)
    }


_PAGE_MIME = {"png": "image/png", "jpg": "image/jpeg"}


def read_page_bytes(stored_path: str, file_type: str, page: int) -> tuple[bytes, str] | None:
    """One page of a stored file as (bytes, media type); None if the file or page is gone."""
    path = Path(stored_path)
    if not path.is_file():
        return None
    try:
        if file_type == "pdf":
            trimmed = render_pdf_page_trimmed(str(path), page - 1)
            return (trimmed or render_pdf_page_webp(str(path), page - 1)), "image/webp"
        if page != 1:
            return None
        data = path.read_bytes()
        return trimmed_image(data) or (data, _PAGE_MIME[file_type])
    except (OSError, RuntimeError, ValueError, KeyError):
        return None
