"""
Gemini API client + PDF page rendering.

Shared rate limiting (global + per-user), prompt caching and transient-error
retry around a single multimodal call. AutoAccounting's extraction prompts live
in services/accounting; this module only knows how to send bytes + a prompt.
"""

import asyncio
import hashlib
import logging
import random
import time
from threading import Lock

import fitz  # PyMuPDF
from google import genai
from google.genai import types

from app.config import settings

logger = logging.getLogger("gemini")

# ---------------------------------------------------------------------------
# Gemini API rate limiters — global (platform-wide) + per-user
# ---------------------------------------------------------------------------

_EVICTION_INTERVAL = 300  # clean up stale user buckets every 5 min
_MAX_TRACKED_USERS = 10_000


class _PerUserRateLimiter:
    """Thread-safe sliding-window rate limiter keyed by user ID.
    Each user gets their own 60-second window capped at `rpm` calls.
    """

    def __init__(self, rpm: int) -> None:
        self._rpm = rpm
        self._window = 60.0
        self._buckets: dict[str, list[float]] = {}
        self._lock = Lock()
        self._last_eviction = time.monotonic()

    def active_user_count(self) -> int:
        """Number of users with at least one call in the trailing window.
        Used by the global limiter to scale the platform RPM dynamically.
        """
        now = time.monotonic()
        cutoff = now - self._window
        with self._lock:
            return sum(1 for ts in self._buckets.values() if ts and ts[-1] > cutoff)

    def _evict_stale(self, now: float) -> None:
        if now - self._last_eviction < _EVICTION_INTERVAL:
            return
        self._last_eviction = now
        cutoff = now - self._window
        stale = [k for k, v in self._buckets.items() if not v or v[-1] < cutoff]
        for k in stale:
            del self._buckets[k]
        if len(self._buckets) > _MAX_TRACKED_USERS:
            sorted_keys = sorted(
                self._buckets.keys(),
                key=lambda k: self._buckets[k][-1] if self._buckets[k] else 0,
            )
            for k in sorted_keys[: len(self._buckets) - _MAX_TRACKED_USERS]:
                del self._buckets[k]

    def acquire(self, user_id: str) -> float:
        """Try to acquire a slot for *user_id*.
        Returns 0.0 if allowed, or seconds to wait if throttled.
        """
        now = time.monotonic()
        with self._lock:
            self._evict_stale(now)
            cutoff = now - self._window
            timestamps = self._buckets.get(user_id, [])
            timestamps = [t for t in timestamps if t > cutoff]
            if len(timestamps) < self._rpm:
                timestamps.append(now)
                self._buckets[user_id] = timestamps
                return 0.0
            wait = timestamps[0] - cutoff
            self._buckets[user_id] = timestamps
            return max(wait, 0.1)


class _GlobalRateLimiter:
    """Thread-safe single-bucket sliding window for the platform-wide ceiling.

    The effective RPM is dynamic: ``rpm_resolver()`` is called on every acquire
    so the limit can scale with the number of active users (see
    ``_resolve_global_rpm`` below).
    """

    def __init__(self, rpm_resolver) -> None:
        self._rpm_resolver = rpm_resolver
        self._window = 60.0
        self._timestamps: list[float] = []
        self._lock = Lock()
        self._last_rpm = 0

    @property
    def last_rpm(self) -> int:
        return self._last_rpm

    def acquire(self) -> float:
        """Returns 0.0 if allowed, or seconds to wait if throttled."""
        rpm = max(1, int(self._rpm_resolver()))
        now = time.monotonic()
        with self._lock:
            self._last_rpm = rpm
            cutoff = now - self._window
            self._timestamps = [t for t in self._timestamps if t > cutoff]
            if len(self._timestamps) < rpm:
                self._timestamps.append(now)
                return 0.0
            wait = self._timestamps[0] - cutoff
            return max(wait, 0.1)


_user_api_limiter = _PerUserRateLimiter(settings.gemini_user_rpm_limit)


def _resolve_global_rpm() -> int:
    """Dynamic platform RPM: scales with concurrently-active users.

    target = active_users * per_user_rpm, clamped to [floor, ceiling].
    """
    active = _user_api_limiter.active_user_count()
    target = active * settings.gemini_user_rpm_limit
    floor = settings.gemini_global_rpm_floor
    ceiling = settings.gemini_global_rpm_ceiling
    if floor > ceiling:
        floor = ceiling
    return max(floor, min(target, ceiling))


_global_api_limiter = _GlobalRateLimiter(_resolve_global_rpm)


# ---------------------------------------------------------------------------
# Gemini prompt context cache
# ---------------------------------------------------------------------------
# Caches the static extraction prompt server-side so each request only pays
# for the variable PDF/image bytes. All failures (model unsupported, below
# minimum token threshold, network) fall back to inline prompt.

_PROMPT_CACHE_REFRESH_BUFFER = 60      # recreate when < 60s of TTL remains
_PROMPT_CACHE_FAILURE_BACKOFF = 3600   # don't retry create for 1h after failure

_prompt_cache_lock = Lock()
_prompt_caches: dict[str, tuple[str, float]] = {}       # key -> (cache_name, monotonic_created_at)
_prompt_cache_failures: dict[str, float] = {}           # key -> monotonic_last_failure_at


def _prompt_cache_key(model: str, prompt: str) -> str:
    h = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]
    return f"{model}:{h}"


def _get_or_create_prompt_cache(client: genai.Client, prompt: str, model: str) -> str | None:
    """Return server-side cache name for the prompt, or None if caching is unavailable.
    Thread-safe. Lazily creates a cache and refreshes near TTL expiry. On any failure
    (e.g. model doesn't support caching, prompt below min tokens) returns None and
    backs off retries for `_PROMPT_CACHE_FAILURE_BACKOFF` seconds.
    """
    if not settings.gemini_enable_prompt_cache:
        return None

    key = _prompt_cache_key(model, prompt)
    ttl = settings.gemini_prompt_cache_ttl_seconds
    now = time.monotonic()

    with _prompt_cache_lock:
        existing = _prompt_caches.get(key)
        if existing:
            name, created_at = existing
            if now - created_at < ttl - _PROMPT_CACHE_REFRESH_BUFFER:
                return name
        last_failure = _prompt_cache_failures.get(key, 0.0)
        if last_failure and now - last_failure < _PROMPT_CACHE_FAILURE_BACKOFF:
            return None

    try:
        cache = client.caches.create(
            model=model,
            config=types.CreateCachedContentConfig(
                system_instruction=prompt,
                ttl=f"{ttl}s",
            ),
        )
        with _prompt_cache_lock:
            _prompt_caches[key] = (cache.name, time.monotonic())
            _prompt_cache_failures.pop(key, None)
        logger.info(
            "gemini_prompt_cache_created name=%s model=%s prompt_chars=%d ttl=%ds",
            cache.name, model, len(prompt), ttl,
        )
        return cache.name
    except Exception as e:
        with _prompt_cache_lock:
            _prompt_cache_failures[key] = time.monotonic()
            _prompt_caches.pop(key, None)
        logger.info(
            "gemini_prompt_cache_unavailable model=%s error=%s (retry after %ds)",
            model, str(e)[:200], _PROMPT_CACHE_FAILURE_BACKOFF,
        )
        return None


def _invalidate_prompt_cache(prompt: str, model: str) -> None:
    key = _prompt_cache_key(model, prompt)
    with _prompt_cache_lock:
        _prompt_caches.pop(key, None)


def _looks_like_cache_error(err: Exception) -> bool:
    msg = str(err).lower()
    return "cachedcontent" in msg or "cached_content" in msg or "cache" in msg and "not found" in msg


def get_pdf_page_count(pdf_path: str) -> int:
    """Return the number of pages in a PDF."""
    doc = fitz.open(pdf_path)
    count = len(doc)
    doc.close()
    return count


def extract_pdf_page(pdf_path: str, page_number: int) -> bytes:
    """Extract a single PDF page as a native single-page PDF. page_number is 0-indexed."""
    doc = fitz.open(pdf_path)
    if page_number >= len(doc):
        doc.close()
        raise ValueError(f"Page {page_number} does not exist (PDF has {len(doc)} pages)")
    new_doc = fitz.open()
    new_doc.insert_pdf(doc, from_page=page_number, to_page=page_number)
    pdf_bytes = new_doc.tobytes()
    new_doc.close()
    doc.close()
    return pdf_bytes


def render_pdf_page(pdf_path: str, page_number: int, dpi: int = 200) -> bytes:
    """Render a single PDF page as a PNG image (used for preview). page_number is 0-indexed."""
    doc = fitz.open(pdf_path)
    if page_number >= len(doc):
        doc.close()
        raise ValueError(f"Page {page_number} does not exist (PDF has {len(doc)} pages)")
    page = doc[page_number]
    pix = page.get_pixmap(dpi=dpi)
    img_bytes = pix.tobytes("png")
    doc.close()
    return img_bytes


def render_pdf_page_jpeg(pdf_path: str, page_number: int, dpi: int = 130, quality: int = 82) -> bytes:
    """Render a PDF page as JPEG (smaller than PNG for scanned content). 0-indexed.

    Kept for the Gemini detection path (proven image/jpeg input). The review
    page is served WebP via render_pdf_page_webp instead.
    """
    doc = fitz.open(pdf_path)
    if page_number >= len(doc):
        doc.close()
        raise ValueError(f"Page {page_number} does not exist (PDF has {len(doc)} pages)")
    page = doc[page_number]
    pix = page.get_pixmap(dpi=dpi)
    img_bytes = pix.tobytes("jpeg", jpg_quality=quality)
    doc.close()
    return img_bytes


def _encode_pixmap_webp(pix, quality: int = 80) -> bytes:
    """Encode a PyMuPDF pixmap to WebP via Pillow (PyMuPDF cannot emit WebP).

    WebP is ~25-40% smaller than JPEG for scanned document pages at equivalent
    quality, with fast encode and decode — the best balance for the review page's
    rapid page-flipping (AVIF compresses more but decodes slower client-side).
    method=4 is Pillow's speed/size balance point.
    """
    return pix.pil_tobytes("WEBP", quality=quality, method=4)


def render_pdf_page_webp(pdf_path: str, page_number: int, dpi: int = 130, quality: int = 80) -> bytes:
    """Render a PDF page as WebP (smaller + faster to transfer than JPEG). 0-indexed."""
    doc = fitz.open(pdf_path)
    if page_number >= len(doc):
        doc.close()
        raise ValueError(f"Page {page_number} does not exist (PDF has {len(doc)} pages)")
    page = doc[page_number]
    pix = page.get_pixmap(dpi=dpi)
    try:
        return _encode_pixmap_webp(pix, quality)
    finally:
        doc.close()


# Blur-up thumbnail: a tiny low-res WebP shown (scaled + blurred) while the
# full page render loads on a cold review page. ~1 KB each — first paint goes
# from spinner to instant blurry page. Width in CSS px; low quality is fine
# since it is always displayed heavily blurred.
_THUMB_WIDTH = 32
_THUMB_QUALITY = 40


def render_pdf_page_thumb_webp(pdf_path: str, page_number: int, target_width: int = _THUMB_WIDTH,
                               quality: int = _THUMB_QUALITY) -> bytes:
    """Render a PDF page as a tiny (~32px-wide) WebP thumbnail for blur-up. 0-indexed."""
    doc = fitz.open(pdf_path)
    if page_number >= len(doc):
        doc.close()
        raise ValueError(f"Page {page_number} does not exist (PDF has {len(doc)} pages)")
    page = doc[page_number]
    try:
        width_pt = page.rect.width or float(target_width)
        zoom = target_width / width_pt
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        return _encode_pixmap_webp(pix, quality)
    finally:
        doc.close()


def get_pdf_page_count_safe(pdf_path: str) -> int:
    """Page count, returns 0 on failure."""
    try:
        return get_pdf_page_count(pdf_path)
    except Exception:
        return 0


def _get_gemini_client() -> genai.Client:
    """Create a Gemini client using the new google-genai SDK."""
    return genai.Client(api_key=settings.gemini_api_key)


# Transient-error retry: Gemini occasionally drops TLS connections mid-response
# under load (SSL: UNEXPECTED_EOF_WHILE_READING) and returns 5xx on overload.
# Without retry, a single hiccup fails the whole chunk and the whole batch.
_GEMINI_MAX_ATTEMPTS = 2
_GEMINI_BASE_BACKOFF = 1.5  # seconds; attempt N waits ~base * 2^(N-1) + jitter

_TRANSIENT_ERROR_HINTS = (
    "UNEXPECTED_EOF",
    "EOF occurred in violation",
    "Connection reset",
    "Connection aborted",
    "Connection refused",
    "Server disconnected",
    "RemoteProtocolError",
    "ReadTimeout",
    "WriteTimeout",
    "ConnectTimeout",
    "Deadline exceeded",
    " 500",
    " 502",
    " 503",
    " 504",
    " 429",
    "InternalServerError",
    "ServiceUnavailable",
    "ResourceExhausted",
)


def _is_transient_gemini_error(exc: BaseException) -> bool:
    """Return True for errors safe to retry (network drops, 5xx, 429)."""
    if isinstance(exc, (ConnectionError, TimeoutError, asyncio.TimeoutError)):
        return True
    # OSError catches the underlying ssl.SSLError and socket-level resets.
    if isinstance(exc, OSError):
        return True
    msg = str(exc)
    return any(hint in msg for hint in _TRANSIENT_ERROR_HINTS)


async def wait_for_quota(user_id: str) -> None:
    """Wait for a slot under the per-user and then the global Gemini RPM limits."""
    while True:
        wait = _user_api_limiter.acquire(user_id)
        if wait == 0:
            break
        logger.info("api_rpm_throttled scope=user user_id=%s wait=%.1fs rpm_limit=%d", user_id, wait, settings.gemini_user_rpm_limit)
        await asyncio.sleep(wait)

    # Global limit protects the shared Gemini quota
    while True:
        wait = _global_api_limiter.acquire()
        if wait == 0:
            break
        logger.info(
            "api_rpm_throttled scope=global wait=%.1fs rpm_limit=%d active_users=%d",
            wait, _global_api_limiter.last_rpm, _user_api_limiter.active_user_count(),
        )
        await asyncio.sleep(wait)


async def _call_gemini(
    client: genai.Client, file_bytes: bytes, mime_type: str, prompt: str, user_id: str,
    model: str, thinking_config: types.ThinkingConfig,
) -> str:
    """Send content to Gemini and return raw text response.
    Enforces per-user RPM limit. Single attempt — retries are handled by the frontend.
    Uses a server-side prompt cache when available; falls back to inline prompt on any
    cache failure so behavior is preserved when caching is unsupported.
    """
    loop = asyncio.get_event_loop()

    # Try to fetch (or lazily create) a prompt cache. Runs in executor since
    # cache.create may make a network call on first use.
    cache_name = await loop.run_in_executor(None, _get_or_create_prompt_cache, client, prompt, model)

    def _do_call(use_cache: bool) -> "object":
        if use_cache and cache_name:
            config = types.GenerateContentConfig(
                response_mime_type="application/json",
                thinking_config=thinking_config,
                cached_content=cache_name,
            )
            contents = [types.Part.from_bytes(data=file_bytes, mime_type=mime_type)]
        else:
            config = types.GenerateContentConfig(
                response_mime_type="application/json",
                thinking_config=thinking_config,
            )
            contents = [
                types.Part.from_bytes(data=file_bytes, mime_type=mime_type),
                prompt,
            ]
        return client.models.generate_content(
            model=model,
            contents=contents,
            config=config,
        )

    await wait_for_quota(user_id)

    async def _call_with_transient_retry(use_cache: bool) -> "object":
        last_exc: BaseException | None = None
        for attempt in range(1, _GEMINI_MAX_ATTEMPTS + 1):
            try:
                return await loop.run_in_executor(None, _do_call, use_cache)
            except Exception as e:
                last_exc = e
                if attempt < _GEMINI_MAX_ATTEMPTS and _is_transient_gemini_error(e):
                    backoff = _GEMINI_BASE_BACKOFF * (2 ** (attempt - 1)) + random.random()
                    logger.warning(
                        "gemini_transient_retry user_id=%s attempt=%d/%d error=%s sleep=%.1fs",
                        user_id, attempt, _GEMINI_MAX_ATTEMPTS, str(e)[:200], backoff,
                    )
                    await asyncio.sleep(backoff)
                    continue
                raise
        assert last_exc is not None
        raise last_exc

    try:
        try:
            response = await _call_with_transient_retry(True)
        except Exception as e:
            # If the cache became invalid server-side (TTL expired between fetch
            # and use, or unsupported), invalidate locally and retry once inline.
            if cache_name and _looks_like_cache_error(e):
                logger.warning(
                    "gemini_cache_invalid_retrying_inline user_id=%s error=%s",
                    user_id, str(e)[:200],
                )
                _invalidate_prompt_cache(prompt, model)
                response = await _call_with_transient_retry(False)
            else:
                raise

        # Best-effort cache-hit logging (field may be absent on older SDKs/models).
        try:
            usage = getattr(response, "usage_metadata", None)
            cached_tokens = getattr(usage, "cached_content_token_count", None) if usage else None
            if cached_tokens:
                logger.info(
                    "gemini_cache_hit user_id=%s cached_tokens=%d model=%s",
                    user_id, cached_tokens, model,
                )
        except Exception:
            pass

        return response.text
    except Exception as e:
        logger.error("gemini_failed user_id=%s error=%s", user_id, str(e)[:200])
        raise RuntimeError(f"Gemini API failed: {e}")
