"""Document page previews render as WebP (smaller + faster than JPEG)."""

import fitz

from app.services.gemini_service import (
    render_pdf_page_jpeg,
    render_pdf_page_webp,
)


def _make_pdf(path, pages: int = 3) -> str:
    doc = fitz.open()
    for _ in range(pages):
        page = doc.new_page(width=612, height=792)
        page.insert_text((72, 72), "BIR FORM 2307 " * 50)
    doc.save(str(path))
    doc.close()
    return str(path)


def _is_webp(data: bytes) -> bool:
    return len(data) > 12 and data[0:4] == b"RIFF" and data[8:12] == b"WEBP"


class TestRenderWebp:
    def test_renders_valid_webp(self, tmp_path):
        pdf = _make_pdf(tmp_path / "a.pdf", pages=1)
        data = render_pdf_page_webp(pdf, 0)
        assert _is_webp(data)

    def test_webp_smaller_than_jpeg(self, tmp_path):
        pdf = _make_pdf(tmp_path / "b.pdf", pages=1)
        webp = render_pdf_page_webp(pdf, 0)
        jpeg = render_pdf_page_jpeg(pdf, 0)
        assert len(webp) < len(jpeg)

    def test_out_of_range_page_raises(self, tmp_path):
        pdf = _make_pdf(tmp_path / "c.pdf", pages=1)
        import pytest
        with pytest.raises(ValueError):
            render_pdf_page_webp(pdf, 5)

