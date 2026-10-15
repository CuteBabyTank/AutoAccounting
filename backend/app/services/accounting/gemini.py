"""Document extraction's entry points into the shared Gemini plumbing.

Reuses ``gemini_service``'s rate limiters, prompt cache and retry with this
package's model and thinking level.
"""

import fitz  # PyMuPDF
from google.genai import types

from app.config import settings
from app.services import gemini_service

# Pages per Gemini call. A scan of many receipts returns one JSON entry per
# document; small chunks keep each reply well inside the output-token limit.
PAGES_PER_CHUNK = 10


async def call_gemini_raw(file_bytes: bytes, mime_type: str, prompt: str, user_id: str) -> str:
    """One Gemini call with an AutoAccounting prompt and AutoAccounting's own model; returns the raw reply text."""
    client = gemini_service._get_gemini_client()
    return await gemini_service._call_gemini(
        client, file_bytes, mime_type, prompt, user_id,
        model=settings.accounting_gemini_model,
        thinking_config=types.ThinkingConfig(thinking_level=settings.accounting_gemini_thinking_level),
    )


def pdf_chunks_for_gemini(pdf_path: str) -> list[tuple[bytes, int, int]]:
    """Split a PDF into compressed chunks of at most ``PAGES_PER_CHUNK`` pages.

    Returns ``(chunk_bytes, start_page_0indexed, end_page_0indexed_inclusive)``.
    """
    source = fitz.open(pdf_path)
    try:
        chunks: list[tuple[bytes, int, int]] = []
        for start in range(0, len(source), PAGES_PER_CHUNK):
            end = min(start + PAGES_PER_CHUNK, len(source)) - 1
            part = fitz.open()
            part.insert_pdf(source, from_page=start, to_page=end)
            chunks.append((part.tobytes(garbage=4, deflate=True), start, end))
            part.close()
        return chunks
    finally:
        source.close()
