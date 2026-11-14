"""Document extraction's entry points into the shared Gemini plumbing.

Reuses ``gemini_service``'s rate limiters, prompt cache and retry with this
package's model and thinking level.
"""

import fitz  # PyMuPDF
import httpx
from google.genai import types

from app.config import settings
from app.services import gemini_service
from app.services.accounting import qwen_reader

# Pages per Gemini call. A scan of many receipts returns one JSON entry per
# document; small chunks keep each reply well inside the output-token limit.
PAGES_PER_CHUNK = 10


class ReaderUnavailable(RuntimeError):
    """The reading service failed (out of credit, quota, outage), not the document."""


async def call_gemini_raw(file_bytes: bytes, mime_type: str, prompt: str, user_id: str,
                          thinking: str | None = None, model: str | None = None,
                          timeout: float | None = None) -> str:
    """One document read with an AutoAccounting prompt; returns the raw (JSON) reply text.

    ``ACCOUNTING_READER`` picks the model: ``qwen`` (see ``qwen_reader``) or ``gemini`` (default). Either way a
    failure of the service itself raises ``ReaderUnavailable``. ``thinking`` / ``model`` / ``timeout`` override the
    reader's usual low-effort settings for one call (format building); left out, nothing changes.
    """
    if settings.accounting_reader.strip().lower() == "qwen":
        try:
            return await qwen_reader.read(file_bytes, mime_type, prompt, user_id, thinking, model, timeout)
        except qwen_reader.ReaderError as e:
            raise ReaderUnavailable(f"Reader failed: {e}") from None
        except httpx.HTTPError as e:  # network failures qwen_reader doesn't map (protocol, read, write, pool)
            raise ReaderUnavailable(f"Reader failed: {type(e).__name__}") from None
    try:
        return await _gemini(file_bytes, mime_type, prompt, user_id, thinking, model)
    except RuntimeError as e:
        if str(e).startswith("Gemini API failed"):
            raise ReaderUnavailable(str(e)[:300]) from None
        raise


async def _gemini(file_bytes: bytes, mime_type: str, prompt: str, user_id: str,
                  thinking: str | None = None, model: str | None = None) -> str:
    client = gemini_service._get_gemini_client()
    level = qwen_reader._effort(thinking) if thinking else settings.accounting_gemini_thinking_level
    return await gemini_service._call_gemini(
        client, file_bytes, mime_type, prompt, user_id,
        model=model or settings.accounting_gemini_model,
        thinking_config=types.ThinkingConfig(thinking_level=level),
    )


def _qwen() -> bool:
    return settings.accounting_reader.strip().lower() == "qwen"


def pages_per_chunk() -> int:
    """Gemini reads 10 pages a call. Qwen's time is mostly writing the reply, so it gets small pieces read side by
    side (``chunks_at_once``): a 10-page PDF takes about as long as one or two pages."""
    return max(1, settings.accounting_reader_pages_per_chunk) if _qwen() else PAGES_PER_CHUNK


def chunks_at_once() -> int:
    return max(1, settings.accounting_reader_parallel) if _qwen() else 3


def pdf_chunk_ranges(page_count: int, size: int | None = None) -> list[tuple[int, int]]:
    """``(start_page_0indexed, end_page_0indexed_inclusive)`` of each chunk, without building any."""
    size = size or pages_per_chunk()
    return [(start, min(start + size, page_count) - 1) for start in range(0, page_count, size)]


def pdf_chunk(pdf_path: str, start: int, end: int, limit: int | None = None) -> bytes:
    """One compressed sub-PDF of pages ``start``..``end``. Built only when it is about to be read, so a file's
    chunks are never all in memory at once (each sub-PDF carries its own copy of every resource its pages
    share). ``limit`` refuses a chunk that expands past that many bytes."""
    source = fitz.open(pdf_path)
    try:
        part = fitz.open()
        try:
            part.insert_pdf(source, from_page=start, to_page=end)
            data = part.tobytes(garbage=4, deflate=True)
        finally:
            part.close()
    finally:
        source.close()
    if limit is not None and len(data) > limit:
        raise ValueError(f"pages {start + 1}-{end + 1} expand to {len(data)} bytes")
    return data


def pdf_chunks_for_gemini(pdf_path: str, size: int | None = None) -> list[tuple[bytes, int, int]]:
    """Every chunk of a PDF at once: ``(chunk_bytes, start_page_0indexed, end_page_0indexed_inclusive)``.
    Small files and tests only; extraction builds chunks one at a time with ``pdf_chunk``."""
    with fitz.open(pdf_path) as source:
        count = len(source)
    return [(pdf_chunk(pdf_path, s, e), s, e) for s, e in pdf_chunk_ranges(count, size)]
