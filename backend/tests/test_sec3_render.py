"""PDF rendering must never parse/draw the file in the web process."""

import asyncio
import subprocess
import threading
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import fitz
import pytest
from fastapi import HTTPException

from app.services import gemini_service
from app.services.accounting import page_trim, pipeline, storage


@pytest.mark.parametrize("render", [gemini_service.render_pdf_page, gemini_service.render_pdf_page_jpeg,
                                     gemini_service.render_pdf_page_webp,
                                     gemini_service.render_pdf_page_thumb_webp,
                                     page_trim.render_pdf_page_trimmed])
def test_all_pdf_helpers_use_a_bounded_child(monkeypatch, tmp_path, render):
    pdf = tmp_path / "page.pdf"
    with fitz.open() as doc:
        doc.new_page().insert_text((72, 72), "Receipt")
        doc.save(pdf)
    calls = []

    def child(argv, **kwargs):
        from pathlib import Path

        calls.append((argv, kwargs))
        Path(argv[-1]).write_bytes(b"isolated image")
        return SimpleNamespace(returncode=0)

    def no_parent_parse(*args, **kwargs):
        pytest.fail("PDF opened in the backend process")

    monkeypatch.setattr(subprocess, "run", child)
    monkeypatch.setattr(fitz, "open", no_parent_parse)
    assert render(str(pdf), 0) == b"isolated image"
    argv, kwargs = calls[0]
    assert argv[1:3] == ["-I", "-c"]
    assert "RLIMIT_AS" in argv[3] and "RLIMIT_CPU" in argv[3]
    assert 0 < int(argv[5]) <= 768 * 1024 * 1024
    assert 0 < int(argv[6]) <= 30
    assert 0 < kwargs["timeout"] <= 30
    assert len(calls) == 1


def test_viewer_worker_timeout_is_not_swallowed_or_retried(monkeypatch, tmp_path):
    pdf = tmp_path / "page.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    calls = []

    def timeout(*args, **kwargs):
        calls.append(1)
        raise subprocess.TimeoutExpired("render", 1)

    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(ValueError, match="Page unavailable"):
        storage.read_page_bytes(str(pdf), "pdf", 1)
    assert len(calls) == 1


async def test_file_page_translates_render_failure_to_page_unavailable(monkeypatch):
    from app.routers import accounting

    file = SimpleNamespace(page_count=1, stored_path="/test/page.pdf", file_type="pdf")
    db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: file)))
    monkeypatch.setattr(accounting, "_scope", lambda user: uuid.uuid4())
    monkeypatch.setattr(accounting, "is_stored_path_safe", lambda path: True)

    def unreadable(*args):
        raise ValueError("Page unavailable: render timed out")

    monkeypatch.setattr(accounting, "read_page_bytes", unreadable)
    with pytest.raises(HTTPException) as error:
        await accounting.file_page(uuid.uuid4(), 1, SimpleNamespace(id=uuid.uuid4()), db)
    assert error.value.status_code in (422, 503)
    assert "Page unavailable" in error.value.detail


async def test_detection_render_failure_stays_in_child(monkeypatch, tmp_path):
    pdf = tmp_path / "page.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("render", 1)

    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(ValueError, match="Page unavailable"):
        await pipeline._first_page(str(pdf), "pdf")


@pytest.mark.parametrize("failure", ["killed", "missing_output"])
def test_worker_failure_never_falls_back_to_parent_render(monkeypatch, tmp_path, failure):
    from app.services.accounting.render_pool import render_page

    pdf = tmp_path / "page.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    child = SimpleNamespace(returncode=-9 if failure == "killed" else 0)
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: child)
    with pytest.raises(ValueError, match="Page unavailable"):
        render_page(str(pdf), 0, "jpeg")


def test_repeated_viewer_requests_use_cached_bytes_and_replacements_invalidate(monkeypatch, tmp_path):
    pdf = tmp_path / "page.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    calls = []

    def child(argv, **kwargs):
        from pathlib import Path

        calls.append(1)
        Path(argv[-1]).write_bytes(b"trimmed webp")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(subprocess, "run", child)
    assert storage.read_page_bytes(str(pdf), "pdf", 1) == (b"trimmed webp", "image/webp")
    assert storage.read_page_bytes(str(pdf), "pdf", 1) == (b"trimmed webp", "image/webp")
    assert len(calls) == 1
    pdf.write_bytes(b"%PDF-1.4 replaced")
    storage.read_page_bytes(str(pdf), "pdf", 1)
    assert len(calls) == 2


async def test_cancellation_does_not_release_running_viewer_slot():
    from app.services.accounting.render_pool import VIEWER_PER_OWNER as PDF_WORKERS, RenderBusy, run_pdf_work

    started, stop = [threading.Event() for _ in range(PDF_WORKERS)], threading.Event()

    def blocking(index):
        started[index].set()
        stop.wait(2)

    tasks = [asyncio.create_task(run_pdf_work(blocking, index, owner="cancel-test"))
             for index in range(PDF_WORKERS)]
    try:
        for event in started:
            assert await asyncio.to_thread(event.wait, 1)
        tasks[0].cancel()
        with pytest.raises(asyncio.CancelledError):
            await tasks[0]
        with pytest.raises(RenderBusy, match="Page unavailable"):
            await run_pdf_work(lambda: None, owner="cancel-test")
    finally:
        stop.set()
        await asyncio.gather(*tasks, return_exceptions=True)

