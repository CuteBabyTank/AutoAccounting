import fitz
import pytest

from app.config import settings
from app.services.accounting import gemini as aa_gemini
from app.services.accounting.gemini import pdf_chunks_for_gemini


@pytest.fixture(autouse=True)
def _gemini_reader(monkeypatch):
    monkeypatch.setattr(settings, "accounting_reader", "gemini")


def test_pdf_chunks_cover_every_page(tmp_path):
    doc = fitz.open()
    for _ in range(3):
        doc.new_page()
    path = tmp_path / "three.pdf"
    doc.save(str(path))
    doc.close()

    chunks = pdf_chunks_for_gemini(str(path))
    assert [(s, e) for _, s, e in chunks] == [(0, 2)]
    assert chunks[0][0].startswith(b"%PDF")


def test_long_pdfs_are_split_into_small_page_chunks(tmp_path):
    doc = fitz.open()
    for _ in range(25):
        doc.new_page()
    path = tmp_path / "long.pdf"
    doc.save(str(path))
    doc.close()

    chunks = pdf_chunks_for_gemini(str(path))
    assert [(s, e) for _, s, e in chunks] == [(0, 9), (10, 19), (20, 24)]
    assert [fitz.open("pdf", b).page_count for b, _, _ in chunks] == [10, 10, 5]


def test_shared_gemini_helpers_we_depend_on_still_exist():
    import inspect

    from app.services import gemini_service

    assert list(inspect.signature(gemini_service._get_gemini_client).parameters) == []
    assert list(inspect.signature(gemini_service._call_gemini).parameters) == [
        "client", "file_bytes", "mime_type", "prompt", "user_id", "model", "thinking_config",
    ]


def test_qwen_reads_small_pieces_side_by_side(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "accounting_reader", "qwen")
    monkeypatch.setattr(settings, "accounting_reader_pages_per_chunk", 2)
    monkeypatch.setattr(settings, "accounting_reader_parallel", 8)
    doc = fitz.open()
    for _ in range(5):
        doc.new_page()
    path = tmp_path / "five.pdf"
    doc.save(str(path))
    doc.close()

    assert [(s, e) for _, s, e in pdf_chunks_for_gemini(str(path))] == [(0, 1), (2, 3), (4, 4)]
    assert aa_gemini.chunks_at_once() == 8
