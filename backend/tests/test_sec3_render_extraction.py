"""Exercise real child renders through the background reader paths."""

import asyncio
import base64
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import fitz
import httpx
import pytest

from app.config import settings
from app.services.accounting import pipeline, render_pool

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="renderer resource limits require Linux")


@pytest.fixture
def pdf(tmp_path: Path) -> Path:
    path = tmp_path / "receipt.pdf"
    with fitz.open() as doc:
        doc.new_page(width=14400, height=14400)
        doc.save(path)
    return path


@pytest.fixture
def qwen_network(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    monkeypatch.setattr(settings, "accounting_reader", "qwen")
    monkeypatch.setattr(settings, "accounting_reader_base_url", "https://reader.test/v1")
    monkeypatch.setattr(settings, "accounting_reader_api_key", "test")
    requests: list[dict] = []

    async def post(self: httpx.AsyncClient, url: str, **kwargs) -> httpx.Response:
        requests.append(kwargs["json"])
        return httpx.Response(200, json={"choices": [{"message": {"content":
            '{"documents":[{"kind":"invoice","doc_number":"SEC3","gross_amount":100}]}'}}]})

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    return requests


async def test_extraction_qwen_rasterizes_in_real_bounded_child(
    pdf: Path, qwen_network: list[dict], monkeypatch: pytest.MonkeyPatch,
) -> None:
    def parent_raster(*args, **kwargs) -> None:
        pytest.fail("uploaded PDF rasterized in backend process")

    monkeypatch.setattr(fitz.Page, "get_pixmap", parent_raster)
    result = await pipeline._read_file(uuid.uuid4(), str(pdf), "pdf", "extract", str(uuid.uuid4()))
    assert result[0][2][0].doc_number == "SEC3"
    content = qwen_network[0]["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": "Page 1:"}
    jpeg = base64.b64decode(content[1]["image_url"]["url"].split(",", 1)[1])
    pix = fitz.Pixmap(jpeg)
    assert pix.width * pix.height <= 3_030_000


@pytest.fixture
def occupied_capacity() -> Iterator[None]:
    # Hold the real admission permits, without replacing the queue or worker boundary.
    acquired = 0
    try:
        for _ in range(2 * render_pool.PDF_WORKERS):
            assert render_pool._PENDING.acquire(blocking=False)
            acquired += 1
        yield
    finally:
        for _ in range(acquired):
            render_pool._PENDING.release()


@pytest.mark.parametrize("path", ["detection", "extraction"])
async def test_background_reader_waits_for_capacity_then_renders(
    pdf: Path, qwen_network: list[dict], occupied_capacity: None, path: str,
) -> None:
    if path == "detection":
        read = pipeline._first_page(str(pdf), "pdf")
    else:
        read = pipeline._read_file(uuid.uuid4(), str(pdf), "pdf", "extract", str(uuid.uuid4()))
    task = asyncio.create_task(read)
    try:
        await asyncio.sleep(0.15)
        assert not task.done(), "ordinary contention must not become an unreadable-file result"
        with pytest.raises(render_pool.RenderBusy):
            await render_pool.run_pdf_work(lambda: None, owner="viewer")
        render_pool._PENDING.release()
        try:
            result = await asyncio.wait_for(task, 20)
            if path == "detection":
                assert result[0].startswith(b"\xff\xd8") and result[1] == "image/jpeg"
            else:
                assert result[0][2][0].doc_number == "SEC3"
        finally:
            assert render_pool._PENDING.acquire(blocking=False)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
