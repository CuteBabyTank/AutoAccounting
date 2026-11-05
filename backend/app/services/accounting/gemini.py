"""Document extraction's entry points into the shared Gemini plumbing.

Reuses ``gemini_service``'s rate limiters, prompt cache and retry with this
package's model and thinking level.
"""

import fitz  # PyMuPDF
from google.genai import types

from app.config import settings
from app.services import gemini_service
from app.services.accounting import qwen_reader

# Pages per Gemini call. A scan of many receipts returns one JSON entry per
# document; small chunks keep each reply well inside the output-token limit.
PAGES_PER_CHUNK = 10


class ReaderUnavailable(RuntimeError):
    """The reading service failed (out of credit, quota, outage), not the document."""


async def call_gemini_raw(file_bytes: bytes, mime_type: str, prompt: str, user_id: str) -> str:
    """One document read with an AutoAccounting prompt; returns the raw (JSON) reply text.

    ``ACCOUNTING_READER`` picks the model: ``qwen`` (see ``qwen_reader``) or ``gemini`` (default). Either way a
    failure of the service itself raises ``ReaderUnavailable``.
    """
    if settings.accounting_reader.strip().lower() == "qwen":
        try:
            return await qwen_reader.read(file_bytes, mime_type, prompt, user_id)
        except qwen_reader.ReaderError as e:
            raise ReaderUnavailable(f"Reader failed: {e}") from None
    try:
        return await _gemini(file_bytes, mime_type, prompt, user_id)
    except RuntimeError as e:
        if str(e).startswith("Gemini API failed"):
            raise ReaderUnavailable(str(e)[:300]) from None
        raise


async def _gemini(file_bytes: bytes, mime_type: str, prompt: str, user_id: str) -> str:
    client = gemini_service._get_gemini_client()
    return await gemini_service._call_gemini(
        client, file_bytes, mime_type, prompt, user_id,
        model=settings.accounting_gemini_model,
        thinking_config=types.ThinkingConfig(thinking_level=settings.accounting_gemini_thinking_level),
    )


def _qwen() -> bool:
    return settings.accounting_reader.strip().lower() == "qwen"


def pages_per_chunk() -> int:
    """Gemini reads 10 pages a call. Qwen's time is mostly writing the reply, so it gets small pieces read side by
    side (``chunks_at_once``): a 10-page PDF takes about as long as one or two pages."""
    return max(1, settings.accounting_reader_pages_per_chunk) if _qwen() else PAGES_PER_CHUNK


def chunks_at_once() -> int:
    return max(1, settings.accounting_reader_parallel) if _qwen() else 3


def pdf_chunks_for_gemini(pdf_path: str, size: int | None = None) -> list[tuple[bytes, int, int]]:
    """Split a PDF into compressed chunks of at most ``PAGES_PER_CHUNK`` pages.

    Returns ``(chunk_bytes, start_page_0indexed, end_page_0indexed_inclusive)``.
    """
    source = fitz.open(pdf_path)
    try:
        chunks: list[tuple[bytes, int, int]] = []
        size = size or pages_per_chunk()
        for start in range(0, len(source), size):
            end = min(start + size, len(source)) - 1
            part = fitz.open()
            part.insert_pdf(source, from_page=start, to_page=end)
            chunks.append((part.tobytes(garbage=4, deflate=True), start, end))
            part.close()
        return chunks
    finally:
        source.close()
