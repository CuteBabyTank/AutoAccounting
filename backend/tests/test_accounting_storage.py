import asyncio
import io

import fitz
import pytest
from starlette.datastructures import UploadFile

from app.services.accounting.storage import UploadRejected, stream_upload


def _upload(name: str, data: bytes) -> UploadFile:
    return UploadFile(file=io.BytesIO(data), filename=name)


def _pdf_bytes(pages: int = 2) -> bytes:
    doc = fitz.open()
    for _ in range(pages):
        doc.new_page()
    data = doc.tobytes()
    doc.close()
    return data


def test_stream_upload_stores_pdf_with_hash_and_pages(tmp_path):
    stored = asyncio.run(stream_upload(_upload("scan.pdf", _pdf_bytes(2)), tmp_path))
    assert stored.file_type == "pdf" and stored.page_count == 2
    assert len(stored.sha256) == 64 and stored.size > 0
    assert stored.stored_path.startswith(str(tmp_path))


def test_stream_upload_rejects_wrong_extension(tmp_path):
    with pytest.raises(UploadRejected, match="only PDF, PNG and JPG"):
        asyncio.run(stream_upload(_upload("sales.xlsx", b"PK\x03\x04data"), tmp_path))


def test_stream_upload_rejects_empty(tmp_path):
    with pytest.raises(UploadRejected, match="is empty"):
        asyncio.run(stream_upload(_upload("blank.pdf", b""), tmp_path))
    assert list(tmp_path.iterdir()) == []


def test_stream_upload_rejects_unreadable_pdf(tmp_path):
    with pytest.raises(UploadRejected, match="couldn't be opened"):
        asyncio.run(stream_upload(_upload("broken.pdf", b"%PDF-1.4 this is not really a pdf"), tmp_path))
    assert list(tmp_path.iterdir()) == []


def test_stream_upload_rejects_mismatched_magic(tmp_path):
    with pytest.raises(UploadRejected):
        asyncio.run(stream_upload(_upload("photo.png", b"GIF89a....."), tmp_path))


def test_is_stored_path_safe_only_inside_root(tmp_path):
    from app.services.accounting.storage import is_stored_path_safe

    root = tmp_path / "acct"
    assert is_stored_path_safe(str(root / "accounting" / "u1" / "a.pdf"), str(root))
    assert not is_stored_path_safe(str(tmp_path / "acct_evil" / "a.pdf"), str(root))
    assert not is_stored_path_safe(str(root / ".." / "secrets.txt"), str(root))


def test_only_files_that_produced_documents_count_as_filed():
    from app.services.accounting.storage import counts_as_filed

    assert counts_as_filed("extracted", 1) is True
    assert counts_as_filed("extracted", 0) is False  # every document soft-deleted
    for status in ("uploaded", "detected", "extracting", "skipped", "error", "duplicate"):
        assert counts_as_filed(status, 0) is False


def _png_bytes() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (40, 40), "white").save(buf, format="PNG")
    return buf.getvalue()


def test_stream_upload_accepts_real_image(tmp_path):
    stored = asyncio.run(stream_upload(_upload("photo.png", _png_bytes()), tmp_path))
    assert stored.file_type == "png" and stored.page_count == 1


def test_stream_upload_rejects_truncated_image(tmp_path):
    data = _png_bytes()
    with pytest.raises(UploadRejected, match="couldn't be opened as an image"):
        asyncio.run(stream_upload(_upload("photo.png", data[: len(data) // 2]), tmp_path))
    assert list(tmp_path.iterdir()) == []


def test_filed_hashes_are_per_company():
    from app.services.accounting.storage import filed_hashes

    rows = [
        ("aaa", "c1", "extracted", 2),
        ("bbb", "c1", "extracted", 0),   # all documents deleted
        ("ccc", "c2", "extracted", 1),   # filed, but for another company
        ("ddd", "c1", "extracting", 0),  # still running
    ]
    assert filed_hashes(rows, "c1") == {"aaa"}
    assert filed_hashes(rows, "c2") == {"ccc"}


def test_read_page_bytes_missing_file_is_none(tmp_path):
    from app.services.accounting.storage import read_page_bytes

    assert read_page_bytes(str(tmp_path / "gone.pdf"), "pdf", 1) is None
    assert read_page_bytes(str(tmp_path / "gone.png"), "png", 1) is None
    png = tmp_path / "ok.png"
    png.write_bytes(_png_bytes())
    data, mime = read_page_bytes(str(png), "png", 1)
    assert mime == "image/png" and data.startswith(b"\x89PNG")
    pdf = tmp_path / "ok.pdf"
    pdf.write_bytes(_pdf_bytes(1))
    data, mime = read_page_bytes(str(pdf), "pdf", 1)
    assert mime == "image/webp" and len(data) > 0


def test_stream_upload_rejects_huge_dimension_images_without_decoding(tmp_path):
    from PIL import Image

    buf = io.BytesIO()
    Image.new("1", (12000, 12000)).save(buf, format="PNG")  # ~144 MP, tiny on disk
    with pytest.raises(UploadRejected, match="too large"):
        asyncio.run(stream_upload(_upload("bomb.png", buf.getvalue()), tmp_path))
    assert list(tmp_path.iterdir()) == []


def test_original_hash_is_only_taken_for_well_formed_jpeg_claims():
    from app.services.accounting.storage import original_hash

    good = "a" * 64
    assert original_hash(good, "jpg") == good
    assert original_hash(good, "pdf") is None and original_hash(good, "png") is None
    assert original_hash("A" * 64, "jpg") is None and original_hash("a" * 63, "jpg") is None
    assert original_hash("", "jpg") is None and original_hash(None, "jpg") is None


def test_stream_upload_keeps_the_browsers_original_hash_for_a_shrunk_photo(tmp_path):
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (40, 30), (200, 10, 10)).save(buf, "JPEG")
    claimed = "b" * 64
    stored = asyncio.run(stream_upload(_upload("photo.jpg", buf.getvalue()), tmp_path, claimed))
    assert stored.sha256 == claimed
    pdf = asyncio.run(stream_upload(_upload("scan.pdf", _pdf_bytes(1)), tmp_path, claimed))
    assert pdf.sha256 != claimed
