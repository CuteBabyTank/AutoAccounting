"""Document reading with a Qwen vision model over an OpenAI-compatible API (OpenRouter by default).

Same contract as the Gemini path: a file (an image, or a PDF chunk) plus an AutoAccounting prompt in, the raw JSON
reply text out. Qwen doesn't take PDFs, so each page of a chunk is rendered to a JPEG and sent in order, labelled
"Page 1", "Page 2"… so page numbers mean the same as when Gemini read the PDF itself.
"""

import asyncio
import base64
import logging
import random
from urllib.parse import urlsplit

import fitz  # PyMuPDF
import httpx

from app.config import settings

logger = logging.getLogger("reader")

DPI = 150  # receipts' small print stays legible; a page is ~1 to 2k image tokens
JPEG_QUALITY = 80
MAX_PIXELS = 3_000_000  # ~A4 at 200 dpi: a PDF with a giant page size can't blow up memory
_slots = asyncio.Semaphore(16)  # reads in flight per instance (several uploads can run at once)


class ReaderError(RuntimeError):
    """The reading service failed (quota, outage, bad reply). The message never contains the document."""


def _base() -> str:
    return (settings.accounting_reader_base_url or settings.assistant_llm_base_url).rstrip("/")


def _key() -> str:
    return settings.accounting_reader_api_key or settings.assistant_llm_api_key


def configured() -> bool:
    return bool(_base() and _key() and settings.accounting_reader_model)


def _zoom(rect: "fitz.Rect") -> float:
    zoom = DPI / 72
    area = max(rect.width, 1) * max(rect.height, 1) * zoom * zoom
    return zoom * min(1.0, (MAX_PIXELS / area) ** 0.5)


def _pdf_pages(data: bytes) -> list[bytes]:
    doc = fitz.open(stream=data, filetype="pdf")
    try:
        pages = []
        for page in doc:  # a chunk is a few pages (pages_per_chunk), each capped at MAX_PIXELS
            z = _zoom(page.rect)
            pages.append(page.get_pixmap(matrix=fitz.Matrix(z, z)).tobytes("jpeg", jpg_quality=JPEG_QUALITY))
        return pages
    finally:
        doc.close()


def _image_part(data: bytes, mime: str) -> dict:
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{base64.b64encode(data).decode()}"}}


async def content_for(file_bytes: bytes, mime_type: str) -> list[dict]:
    if mime_type == "application/pdf":
        pages = await asyncio.get_running_loop().run_in_executor(None, _pdf_pages, file_bytes)
        parts: list[dict] = []
        for n, page in enumerate(pages, 1):
            parts.append({"type": "text", "text": f"Page {n}:"})
            parts.append(_image_part(page, "image/jpeg"))
        return parts
    return [_image_part(file_bytes, mime_type)]


def _payload(content: list[dict], prompt: str) -> dict:
    payload = {
        "model": settings.accounting_reader_model,
        "messages": [{"role": "user", "content": [*content, {"type": "text", "text": prompt}]}],
        "temperature": 0,
        "max_tokens": settings.accounting_reader_max_output_tokens,
        "response_format": {"type": "json_object"},
    }
    host = urlsplit(_base()).hostname or ""
    if host == "openrouter.ai":
        payload["reasoning"] = {"enabled": False}
        # Clients' tax documents: only hosts that neither keep nor train on what they're sent, fastest first.
        payload["provider"] = {"sort": "throughput", "data_collection": "deny"}
    elif host == "dashscope.aliyuncs.com" or (host.startswith("dashscope-") and host.endswith(".aliyuncs.com")):
        payload["enable_thinking"] = False
    return payload


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else ""
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t.strip()


async def read(file_bytes: bytes, mime_type: str, prompt: str, user_id: str) -> str:
    if not configured():
        raise ReaderError("reader_not_configured")
    headers = {"Authorization": f"Bearer {_key()}"}
    timeout = httpx.Timeout(settings.accounting_reader_timeout_seconds, connect=10)
    async with _slots, httpx.AsyncClient(timeout=timeout) as client:  # the slot also bounds page rendering
        payload = _payload(await content_for(file_bytes, mime_type), prompt)
        for attempt in range(3):
            retry = attempt < 2
            try:
                r = await client.post(f"{_base()}/chat/completions", json=payload, headers=headers)
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as e:
                if not retry:
                    raise ReaderError(f"reader_unreachable {type(e).__name__}") from None
                await asyncio.sleep(1.5 * (attempt + 1) + random.random())
                continue
            if r.status_code == 429 or r.status_code >= 500:
                if not retry:
                    raise ReaderError(f"reader_http_{r.status_code}")
                wait = r.headers.get("retry-after")
                await asyncio.sleep(min(float(wait), 20) if wait and wait.replace(".", "", 1).isdigit()
                                    else 1.5 * (attempt + 1) + random.random())
                continue
            if r.status_code >= 400:
                raise ReaderError(f"reader_http_{r.status_code}")
            body = r.json()
            choice = (body.get("choices") or [{}])[0]
            text = ((choice.get("message") or {}).get("content") or "")
            if isinstance(text, list):  # some providers return content parts
                text = "".join(p.get("text", "") for p in text if isinstance(p, dict))
            usage = body.get("usage") or {}
            logger.info("reader_call model=%s user_id=%s prompt_tokens=%s completion_tokens=%s finish=%s",
                        settings.accounting_reader_model, user_id, usage.get("prompt_tokens"),
                        usage.get("completion_tokens"), choice.get("finish_reason"))
            if not text.strip():
                if retry:
                    continue
                raise ReaderError("reader_empty_reply")
            return _strip_fences(text)
    raise ReaderError("reader_failed")
