"""Compression and rendering share the instance's PDF child memory allowance."""

import asyncio
import sys
import threading
from pathlib import Path

import fitz
import pytest

from app.services.accounting import compress, pipeline, render_pool

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="child resource limits require Linux")


async def test_shared_budget_waits_for_background_work_and_refuses_viewer(tmp_path: Path) -> None:
    from app.services.accounting import pdf_budget

    pdf = tmp_path / "receipt.pdf"
    with fitz.open() as doc:
        doc.new_page().insert_text((72, 72), "Shared PDF budget")
        doc.save(pdf)
    # Reserve all three child allowances, regardless of which pool owns them.
    held = 0
    tasks = []
    entered = threading.Event()

    def rewrite():
        entered.set()
        return compress.compress_file(str(pdf), "pdf")

    try:
        for _ in range(3):
            assert pdf_budget.PDF_CHILD_SLOTS.acquire(blocking=False)
            held += 1
        assert not pdf_budget.PDF_CHILD_SLOTS.acquire(blocking=False)
        assert compress.PDF_MEMORY_BYTES == render_pool.PDF_MEMORY_BYTES == 768 * 1024 * 1024
        assert 3 * compress.PDF_MEMORY_BYTES + pdf_budget.PARENT_HEADROOM_BYTES <= 4096 * 1024 * 1024
        assert pdf_budget.PARENT_HEADROOM_BYTES >= 1024 * 1024 * 1024

        # Use separate files so rewriting cannot race the render's stat/cache key.
        rendered = tmp_path / "render.pdf"
        rendered.write_bytes(pdf.read_bytes())
        tasks.append(asyncio.get_running_loop().run_in_executor(compress.PDF_POOL, rewrite))
        assert await asyncio.to_thread(entered.wait, 2)
        tasks.append(asyncio.create_task(pipeline._first_page(str(rendered), "pdf")))
        await asyncio.sleep(0.15)
        assert all(not task.done() for task in tasks)
        with pytest.raises(render_pool.RenderBusy, match="Page unavailable"):
            await render_pool.run_pdf_work(render_pool.render_page, str(rendered), 0, "jpeg", owner="viewer")

        # One available allowance lets both pools make progress in turn.
        pdf_budget.PDF_CHILD_SLOTS.release()
        held -= 1
        rewritten, (image, mime) = await asyncio.wait_for(asyncio.gather(*tasks), 30)
        assert rewritten.path == str(pdf) and rewritten.size > 0
        assert image.startswith(b"\xff\xd8") and mime == "image/jpeg"
    finally:
        for _ in range(held):
            pdf_budget.PDF_CHILD_SLOTS.release()
        await asyncio.gather(*tasks, return_exceptions=True)


def test_failed_children_release_the_shared_budget(tmp_path: Path) -> None:
    from app.services.accounting import pdf_budget

    invalid = tmp_path / "broken.pdf"
    invalid.write_bytes(b"%PDF-1.4 broken")
    assert compress.compress_file(str(invalid), "pdf").size == len(b"%PDF-1.4 broken")
    with pytest.raises(ValueError, match="Page unavailable"):
        render_pool.render_page(str(invalid), 0, "jpeg")
    acquired = 0
    try:
        for _ in range(3):
            assert pdf_budget.PDF_CHILD_SLOTS.acquire(blocking=False)
            acquired += 1
    finally:
        for _ in range(acquired):
            pdf_budget.PDF_CHILD_SLOTS.release()
