"""Bounded PDF rasterization. Only the disposable child imports/draws untrusted PDFs."""

import asyncio
import logging
import subprocess
import sys
import tempfile
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from threading import BoundedSemaphore, Lock, local
from typing import TypeVar

from app.services.accounting.pdf_budget import BACKGROUND_CHILD_SLOTS, PDF_CHILD_SLOTS, PDF_MEMORY_BYTES

logger = logging.getLogger(__name__)
PDF_WORKERS = 3
# Background readers (wait=True) may occupy at most this many pool threads / pending slots, so a
# viewer never queues behind extraction and always finds a free thread.
BACKGROUND_WORKERS = PDF_WORKERS - 1
# Duplicate comparison legitimately loads two documents side by side.
VIEWER_PER_OWNER = 2
# Each 768 MiB child also needs a shared pdf_budget permit: compression and rendering
# together leave explicit parent/buffer headroom, regardless of the two pools' worker counts.
PDF_CPU_S = 10
PDF_TIMEOUT_S = 15
MAX_RENDER_BYTES = 128 * 1024 * 1024
PDF_POOL = ThreadPoolExecutor(max_workers=PDF_WORKERS, thread_name_prefix="pdf-render")
_WORKERS = BoundedSemaphore(PDF_WORKERS)
_PENDING = BoundedSemaphore(2 * PDF_WORKERS)
_BACKGROUND = BoundedSemaphore(BACKGROUND_WORKERS)
_THREAD = local()  # marks the pool thread's current job as background work for render_page
_LOCK = Lock()
_OWNERS: dict[str, int] = {}
_APP_ROOT = str(Path(__file__).resolve().parents[3])
_T = TypeVar("_T")

# Small, byte-bounded viewer cache; files are immutable, but stat identity also invalidates replacements.
_CACHE_LIMIT = 32 * 1024 * 1024
_CACHE: OrderedDict[tuple, bytes | None] = OrderedDict()
_CACHE_BYTES = 0


class RenderBusy(ValueError):
    """The render queue or this viewer's concurrency allowance is full."""


async def run_pdf_work(fn: Callable[..., _T], *args: object, owner: str | None = None, wait: bool = False) -> _T:
    """Bound submitted work; background readers wait cancellably, viewers fail promptly when full.

    Background work is limited to BACKGROUND_WORKERS of the pool and two of the three PDF children,
    so interactive renders keep capacity while extraction or compression runs."""
    while True:
        try:
            return await _submit_pdf_work(fn, *args, owner=owner, background=wait)
        except RenderBusy:
            if not wait:
                raise
            await asyncio.sleep(0.05)


async def _submit_pdf_work(fn: Callable[..., _T], *args: object, owner: str | None,
                           background: bool = False) -> _T:
    with _LOCK:
        if owner is not None and _OWNERS.get(owner, 0) >= VIEWER_PER_OWNER:
            raise RenderBusy("Page unavailable: another page is still rendering")
        if background and not _BACKGROUND.acquire(blocking=False):
            raise RenderBusy("Background renders are at their share")
        if not _PENDING.acquire(blocking=False):
            if background:
                _BACKGROUND.release()
            raise RenderBusy("Page unavailable: renderer is busy")
        if owner is not None:
            _OWNERS[owner] = _OWNERS.get(owner, 0) + 1

    def release(_future: Future[_T] | None) -> None:
        with _LOCK:
            _PENDING.release()
            if background:
                _BACKGROUND.release()
            if owner is not None:
                remaining = _OWNERS[owner] - 1
                if remaining:
                    _OWNERS[owner] = remaining
                else:
                    del _OWNERS[owner]

    try:
        future = PDF_POOL.submit(_run_marked, background, fn, *args)
    except Exception:
        release(None)
        raise
    # A cancelled coroutine must not free the slot while its subprocess is still running.
    future.add_done_callback(release)
    return await asyncio.wrap_future(future)


def _run_marked(background: bool, fn: Callable[..., _T], *args: object) -> _T:
    _THREAD.background = background
    try:
        return fn(*args)
    finally:
        _THREAD.background = False


_WORKER = """
import resource, sys
memory, cpu, output = map(int, sys.argv[2:5])
resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
resource.setrlimit(resource.RLIMIT_FSIZE, (output, output))
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from app.services.accounting.render_pool import _render_local
data = _render_local(sys.argv[5], int(sys.argv[6]), sys.argv[7], int(sys.argv[8]),
                     int(sys.argv[9]), int(sys.argv[10]))
Path(sys.argv[11]).write_bytes(data or b'')
"""


def render_page(pdf_path: str, page: int, kind: str, dpi: int = 130, quality: int = 80,
                target_width: int = 32) -> bytes | None:
    """Blocking isolated render; None means only that a trim was unnecessary, never worker failure."""
    global _CACHE_BYTES
    try:
        stat = Path(pdf_path).stat()
        key = (str(Path(pdf_path).resolve()), stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns,
               page, kind, dpi, quality, target_width)
    except OSError as exc:
        raise ValueError("Page unavailable: file could not be opened") from exc
    with _LOCK:
        if key in _CACHE:
            _CACHE.move_to_end(key)
            return _CACHE[key]
    background = bool(getattr(_THREAD, "background", False))
    if not _WORKERS.acquire(blocking=False):
        raise RenderBusy("Page unavailable: renderer is busy")
    if background:
        # Background renders wait for their share (at most two children with compression), on one of
        # at most BACKGROUND_WORKERS threads, leaving a thread and a child for the viewer.
        BACKGROUND_CHILD_SLOTS.acquire()
        PDF_CHILD_SLOTS.acquire()
    elif not PDF_CHILD_SLOTS.acquire(blocking=False):
        _WORKERS.release()
        raise RenderBusy("Page unavailable: PDF workers are busy")
    try:
        with tempfile.TemporaryDirectory(prefix="aa-render-") as folder:
            dest = Path(folder) / "page.image"
            try:
                proc = subprocess.run(
                    [sys.executable, "-I", "-c", _WORKER, _APP_ROOT, str(PDF_MEMORY_BYTES), str(PDF_CPU_S),
                     str(MAX_RENDER_BYTES), str(Path(pdf_path).resolve()), str(page), kind, str(dpi), str(quality),
                     str(target_width), str(dest)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=PDF_TIMEOUT_S, check=False,
                )
            except subprocess.TimeoutExpired as exc:
                logger.warning("accounting_render_failed error=timeout page=%d", page)
                raise ValueError("Page unavailable: render timed out") from exc
            if proc.returncode != 0 or not dest.is_file():
                logger.warning("accounting_render_failed error=worker_exit_%d page=%d", proc.returncode, page)
                raise ValueError("Page unavailable: PDF could not be rendered")
            with dest.open("rb") as stream:
                data = stream.read(MAX_RENDER_BYTES + 1)
            if len(data) > MAX_RENDER_BYTES or (not data and kind != "trimmed"):
                raise ValueError("Page unavailable: invalid render output")
    except OSError as exc:
        raise ValueError("Page unavailable: renderer could not read the page") from exc
    finally:
        PDF_CHILD_SLOTS.release()
        if background:
            BACKGROUND_CHILD_SLOTS.release()
        _WORKERS.release()
    if len(data) <= _CACHE_LIMIT:
        with _LOCK:
            previous = _CACHE.pop(key, b"")
            _CACHE_BYTES -= len(previous or b"")
            while _CACHE and (_CACHE_BYTES + len(data) > _CACHE_LIMIT or len(_CACHE) >= 128):
                _CACHE_BYTES -= len(_CACHE.popitem(last=False)[1] or b"")
            _CACHE[key] = data or None
            _CACHE_BYTES += len(data)
    return data or None


def _render_local(pdf_path: str, page_number: int, kind: str, dpi: int, quality: int,
                  target_width: int) -> bytes | None:
    """Child entry point. Keep codecs and trim calculations identical to the original helpers."""
    import fitz

    from app.services.pdf_render import render_zoom

    if kind == "trimmed":
        from app.services.accounting.page_trim import _render_pdf_page_trimmed

        return _render_pdf_page_trimmed(pdf_path, page_number)
    with fitz.open(pdf_path) as doc:
        if not 0 <= page_number < len(doc):
            raise ValueError("Page does not exist")
        page = doc[page_number]
        if kind == "thumb":
            dpi = 72 * target_width / (page.rect.width or float(target_width))
        zoom = render_zoom(page.rect.width, page.rect.height, dpi)
        if kind == "qwen":
            from app.services.accounting.qwen_reader import _zoom

            zoom = min(zoom, _zoom(page.rect))
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        if kind in ("webp", "thumb"):
            return pix.pil_tobytes("WEBP", quality=quality, method=4)
        if kind in ("jpeg", "qwen"):
            return pix.tobytes("jpeg", jpg_quality=quality)
        if kind == "png":
            return pix.tobytes("png")
        raise ValueError("Unknown render format")
