"""Background PDF work (readers, compression) never takes the page viewer's render capacity."""

import asyncio
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.services.accounting import compress, pdf_budget, render_pool


def _pdf(path: Path) -> str:
    path.write_bytes(b"%PDF-1.4 stand-in; the child process is the mocked boundary")
    return str(path)


async def test_viewer_gets_a_slot_while_background_pollers_saturate_the_pool() -> None:
    stop = threading.Event()

    def background_job() -> None:
        stop.wait(0.5)

    pollers = [asyncio.create_task(render_pool.run_pdf_work(background_job, wait=True)) for _ in range(8)]
    try:
        await asyncio.sleep(0.1)
        for _ in range(10):  # the reviewer's scenario: viewer requests while 8 pollers keep retrying
            assert await render_pool.run_pdf_work(lambda: b"page", owner="viewer") == b"page"
            await asyncio.sleep(0.05)
        assert not all(p.done() for p in pollers), "background work was still saturating its share"
    finally:
        stop.set()
        await asyncio.gather(*pollers)


async def test_viewer_renders_while_extraction_and_compression_hold_their_children(monkeypatch, tmp_path) -> None:
    lock = threading.Lock()
    live = {"all": 0, "background": 0}
    peak = {"all": 0, "background": 0}

    def child(argv, **kwargs):
        viewer = "webp" in argv  # the viewer asks for WebP; readers JPEG; compression has no kind
        with lock:
            live["all"] += 1
            live["background"] += 0 if viewer else 1
            peak["all"] = max(peak["all"], live["all"])
            peak["background"] = max(peak["background"], live["background"])
        try:
            time.sleep(0.3)
            Path(argv[-1]).write_bytes(b"image")
            return SimpleNamespace(returncode=0)
        finally:
            with lock:
                live["all"] -= 1
                live["background"] -= 0 if viewer else 1

    monkeypatch.setattr(subprocess, "run", child)
    loop = asyncio.get_running_loop()

    async def reader(n: int) -> None:  # detection/extraction renders several pages per file
        for page in range(3):
            await render_pool.run_pdf_work(render_pool.render_page, _pdf(tmp_path / f"bg{n}-{page}.pdf"), page,
                                           "jpeg", wait=True)

    def compression(n: int) -> bool:
        src = Path(_pdf(tmp_path / f"upload{n}.pdf"))
        return compress._pdf_file_isolated(src, tmp_path / f"upload{n}.out.pdf")

    background = [asyncio.create_task(reader(n)) for n in range(8)]
    background += [loop.run_in_executor(compress.PDF_POOL, compression, n) for n in range(3)]
    viewer_pdf = _pdf(tmp_path / "viewer.pdf")
    try:
        await asyncio.sleep(0.1)
        for page in range(5):  # a person flipping pages while everything else runs
            assert await render_pool.run_pdf_work(render_pool.render_page, viewer_pdf, page, "webp",
                                                  owner="viewer") == b"image"
        assert not all(t.done() for t in background)
    finally:
        await asyncio.wait_for(asyncio.gather(*background), 60)
    # The memory budget is unchanged: never more than three children, at most two of them background.
    assert peak["all"] <= 3 and peak["background"] <= 2
    assert 3 * pdf_budget.PDF_MEMORY_BYTES + pdf_budget.PARENT_HEADROOM_BYTES <= 4096 * 1024 * 1024
    for sem, n in ((pdf_budget.PDF_CHILD_SLOTS, 3), (pdf_budget.BACKGROUND_CHILD_SLOTS, 2)):
        assert all(sem.acquire(blocking=False) for _ in range(n))
        for _ in range(n):
            sem.release()


async def test_background_render_waits_instead_of_failing_when_its_share_is_held(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(subprocess, "run", lambda argv, **kw: (Path(argv[-1]).write_bytes(b"jpeg"),
                                                             SimpleNamespace(returncode=0))[1])
    assert pdf_budget.BACKGROUND_CHILD_SLOTS.acquire(blocking=False)
    assert pdf_budget.BACKGROUND_CHILD_SLOTS.acquire(blocking=False)
    released = False
    task = asyncio.create_task(render_pool.run_pdf_work(render_pool.render_page, _pdf(tmp_path / "bg.pdf"), 0,
                                                        "jpeg", wait=True))
    try:
        await asyncio.sleep(0.2)
        assert not task.done()
        # The viewer still renders through the reserved child.
        assert await render_pool.run_pdf_work(render_pool.render_page, _pdf(tmp_path / "v.pdf"), 0, "webp",
                                              owner="viewer") == b"jpeg"
        pdf_budget.BACKGROUND_CHILD_SLOTS.release()
        released = True
        assert await asyncio.wait_for(task, 5) == b"jpeg"
    finally:
        pdf_budget.BACKGROUND_CHILD_SLOTS.release()
        if not released:
            pdf_budget.BACKGROUND_CHILD_SLOTS.release()
        await asyncio.gather(task, return_exceptions=True)


async def test_page_route_still_answers_503_when_the_viewer_itself_is_full(monkeypatch) -> None:
    # The frontend retries a 503 once (accountingApi.pageImage); the server contract is unchanged.
    import uuid

    from app.models.user import User, UserRole
    from app.routers import accounting

    user = User(id=uuid.uuid4(), role=UserRole.ENTERPRISE)
    row = SimpleNamespace(id=uuid.uuid4(), page_count=3, stored_path="/x.pdf", file_type="pdf")

    class DB:
        async def execute(self, stmt):
            return SimpleNamespace(scalar_one_or_none=lambda: row)

    async def busy(*args, **kwargs):
        raise render_pool.RenderBusy("Page unavailable: renderer is busy")

    monkeypatch.setattr(accounting, "is_stored_path_safe", lambda path: True)
    monkeypatch.setattr(render_pool, "run_pdf_work", busy)
    with pytest.raises(HTTPException) as error:
        await accounting.file_page(row.id, 1, user=user, db=DB())
    assert error.value.status_code == 503
