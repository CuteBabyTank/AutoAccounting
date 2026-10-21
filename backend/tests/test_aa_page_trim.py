import io

import fitz
from PIL import Image, ImageDraw

from app.services.accounting.page_trim import content_box, render_pdf_page_trimmed, trimmed_image


def _page(size=(800, 1000), box=(300, 100, 500, 400), paper=(250, 250, 250), dust=False) -> Image.Image:
    img = Image.new("RGB", size, paper)
    draw = ImageDraw.Draw(img)
    draw.rectangle(box, outline=(20, 20, 20), width=3)
    draw.text((box[0] + 20, box[1] + 20), "TOTAL 680.00", fill=(0, 0, 0))
    if dust:
        img.putpixel((790, 990), (0, 0, 0))
    return img


def _png(img: Image.Image) -> bytes:
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def test_small_receipt_on_a_page_is_cropped_with_a_margin():
    left, top, right, bottom = content_box(_page(dust=True))
    assert 280 <= left < 300 and 80 <= top < 100 and 500 < right <= 520 and 400 < bottom <= 420


def test_full_pages_photos_and_blank_pages_are_left_alone():
    assert content_box(_page(box=(10, 10, 790, 990))) is None              # content edge to edge
    assert content_box(_page(paper=(90, 70, 60))) is None                  # a photo on a dark table
    assert content_box(Image.new("RGB", (800, 1000), "white")) is None     # nothing printed


def test_trimmed_image_returns_webp_or_none():
    data, mime = trimmed_image(_png(_page()))
    assert mime == "image/webp" and Image.open(io.BytesIO(data)).size[0] < 300
    assert trimmed_image(_png(_page(box=(10, 10, 790, 990)))) is None
    assert trimmed_image(b"not an image") is None


def test_pdf_page_is_clipped_and_rendered_sharper(tmp_path):
    pdf = tmp_path / "pack.pdf"
    doc = fitz.open()
    small = doc.new_page(width=612, height=792)
    small.insert_text((250, 120), "MANG TOMAS SARI-SARI STORE", fontsize=9)
    small.draw_rect(fitz.Rect(240, 100, 380, 300), color=(0, 0, 0))
    full = doc.new_page(width=612, height=792)
    full.draw_rect(fitz.Rect(10, 10, 602, 782), color=(0, 0, 0))
    doc.save(pdf)
    doc.close()
    img = Image.open(io.BytesIO(render_pdf_page_trimmed(str(pdf), 0)))
    w, h = img.size
    assert abs(w / h - 140 / 200) < 0.15            # the receipt's shape, not the page's
    assert w > 140 * 130 / 72                        # drawn at more than the viewer's usual 130 dpi
    assert render_pdf_page_trimmed(str(pdf), 1) is None
    assert render_pdf_page_trimmed(str(pdf), 5) is None
