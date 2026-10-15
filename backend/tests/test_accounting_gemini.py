import fitz

from app.services.accounting.gemini import pdf_chunks_for_gemini


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
