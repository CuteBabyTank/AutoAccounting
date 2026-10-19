"""Uploads are kept smaller: photos downsized/re-encoded, PDFs rewritten, nothing unsafe or not worth it."""

import asyncio
import hashlib
import io
import random

import pymupdf
from fastapi import UploadFile
from PIL import Image

from app.services.accounting.compress import MAX_SIDE, compress_bytes, compress_file
from app.services.accounting.storage import stream_upload


def _photo(w: int = 4000, h: int = 3000, mode: str = "RGB", fmt: str = "JPEG", quality: int = 98) -> bytes:
    rnd = random.Random(7)
    img = Image.new(mode, (w // 8, h // 8))
    img.putdata([tuple(rnd.randrange(256) for _ in mode) if len(mode) > 1 else rnd.randrange(256)
                 for _ in range((w // 8) * (h // 8))])
    img = img.resize((w, h), Image.Resampling.BICUBIC)
    buf = io.BytesIO()
    img.save(buf, fmt, **({"quality": quality} if fmt == "JPEG" else {}))
    return buf.getvalue()


def _scanned_pdf(pages: int = 2) -> bytes:
    doc = pymupdf.open()
    for _ in range(pages):
        page = doc.new_page(width=595, height=842)
        page.insert_image(page.rect, stream=_photo(2480, 3508, quality=98))  # A4 at 300 dpi
        page.insert_text((72, 72), "SALES INVOICE No. 0001")
    return doc.tobytes()


def test_a_big_phone_photo_is_downsized_to_a_jpeg():
    data = _photo()
    out, kind = compress_bytes(data, "jpg")
    assert kind == "jpg" and len(out) < len(data) / 2
    with Image.open(io.BytesIO(out)) as img:
        assert max(img.size) == MAX_SIDE


def test_a_png_photo_with_transparency_becomes_a_flat_jpeg():
    data = _photo(1200, 900, mode="RGBA", fmt="PNG")
    out, kind = compress_bytes(data, "png")
    assert kind == "jpg"
    with Image.open(io.BytesIO(out)) as img:
        assert img.mode == "RGB"


def test_a_small_already_compact_file_is_left_alone():
    assert compress_bytes(_photo(400, 300, quality=60), "jpg") is None


def test_a_scanned_pdf_keeps_its_pages_and_text_but_shrinks():
    data = _scanned_pdf()
    out, kind = compress_bytes(data, "pdf")
    assert kind == "pdf" and len(out) < len(data) * 0.7
    with pymupdf.open(stream=out, filetype="pdf") as doc:
        assert doc.page_count == 2
        assert "SALES INVOICE No. 0001" in doc[0].get_text()
        width = doc.extract_image(doc[0].get_images()[0][0])["width"]
        assert width <= 1700  # 300 dpi scan brought down to about 200 dpi (A4 is 8.27 in wide)


def test_unreadable_input_is_kept_as_is():
    assert compress_bytes(b"%PDF-1.4 broken", "pdf") is None
    assert compress_bytes(b"not an image", "jpg") is None


def test_compress_file_replaces_in_place_and_renames_a_png(tmp_path):
    src = tmp_path / "x.png"
    src.write_bytes(_photo(1200, 900, mode="RGBA", fmt="PNG"))
    kept = compress_file(str(src), "png")
    assert kept.file_type == "jpg" and kept.path.endswith("x.jpg")
    assert not src.exists() and (tmp_path / "x.jpg").stat().st_size == kept.size < kept.original_size


def test_stream_upload_keeps_the_small_copy_but_the_original_hash(tmp_path):
    data = _photo()
    upload = UploadFile(filename="receipt.jpg", file=io.BytesIO(data))
    stored = asyncio.run(stream_upload(upload, tmp_path))
    assert stored.sha256 == hashlib.sha256(data).hexdigest()
    assert stored.size < len(data) / 2
    assert len(list(tmp_path.iterdir())) == 1


def test_a_pdf_declaring_a_huge_image_is_kept_as_is():
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_image(page.rect, stream=_photo(800, 600))
    xref = page.get_images()[0][0]
    doc.xref_set_key(xref, "Width", "20000")
    doc.xref_set_key(xref, "Height", "20000")  # 400 megapixels declared
    assert compress_bytes(doc.tobytes(), "pdf") is None
