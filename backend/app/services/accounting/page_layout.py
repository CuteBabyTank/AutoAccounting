"""What the browser needs to place field boxes on a page it shows: the region the viewer's trimmed image covers
(`crop`), the untrimmed page's width / height (`aspect`) and, for a PDF with a text layer, its words with positions.
All coordinates are fractions of the untrimmed page. Computed only when a page is opened (no OCR here: scans are
read in the person's browser).
"""

import io

from PIL import Image

from app.services.accounting.page_trim import content_box

MAX_WORDS = 5000
_FULL = [0, 0, 1, 1]


def _r(v: float) -> float:
    return round(v, 5)


FEW_WORDS = 40          # a scan's stray text (a "Scanned with ..." line, page numbers) is about this many words
IMAGE_SHARE = 0.5       # ...on a page mostly covered by one picture


def _mostly_image(page, word_count: int) -> bool:
    """A scanned page carrying a little text: its words aren't the document's, so the browser OCRs the picture."""
    if word_count > FEW_WORDS:
        return False
    import fitz

    area = abs(page.rect) or 1.0
    try:
        covered = max((abs(page.rect & fitz.Rect(i["bbox"])) for i in page.get_image_info()), default=0)
    except (ValueError, RuntimeError):
        return False
    return covered / area >= IMAGE_SHARE


def _pdf_layout_local(pdf_path: str, page_number: int) -> dict:
    """Child-only (render_pool kind "layout"): parsing the PDF stays in the memory-capped child."""
    import fitz

    from app.services.accounting.page_trim import pdf_clip

    with fitz.open(pdf_path) as doc:
        if not 0 <= page_number < len(doc):
            raise ValueError("Page does not exist")
        page = doc[page_number]
        return layout_of_page(page, pdf_clip(page))


def layout_of_page(page, clip) -> dict:
    """A page's layout given the viewer's trim (`page_trim.pdf_clip`); the trimmed render computes it with the clip
    it already has, so viewing a page costs one child for the image and its layout."""
    import fitz

    r = page.rect
    w, h = r.width or 1.0, r.height or 1.0
    crop = _FULL if clip is None else [_r((clip.x0 - r.x0) / w), _r((clip.y0 - r.y0) / h),
                                       _r((clip.x1 - r.x0) / w), _r((clip.y1 - r.y0) / h)]
    raw = page.get_text("words")
    # Words come in the unrotated page's space; page.rect and the trim are the page as shown.
    m = page.rotation_matrix
    boxes = [(fitz.Rect(x0, y0, x1, y1) * m, text) for x0, y0, x1, y1, text, *_ in raw]
    scanned = _mostly_image(page, len(raw))
    text_layer = 0 < len(raw) <= MAX_WORDS and not scanned
    words = [[_r((b.x0 - r.x0) / w), _r((b.y0 - r.y0) / h), _r((b.x1 - r.x0) / w), _r((b.y1 - r.y0) / h),
              str(text)[:100]] for b, text in boxes] if text_layer else []
    return {"crop": crop, "aspect": w / h, "words": words, "text_layer": text_layer}


def image_layout(data: bytes) -> dict:
    """An image page: no words (the browser reads it), the trim region as `page_trim.trimmed_image` cuts it. A photo
    still carrying an EXIF rotation gets `crop: None` (the browser and the reader may not agree on which way is up,
    so the browser draws nothing)."""
    from app.services.accounting.compress import image_decode_slot

    with Image.open(io.BytesIO(data)) as img:
        w, h = img.size
        if img.getexif().get(0x0112, 1) not in (0, 1):
            return {"crop": None, "aspect": w / h, "words": [], "text_layer": False}
        with image_decode_slot(w * h):
            img.load()
            box = content_box(img)
    crop = _FULL if box is None else [_r(box[0] / w), _r(box[1] / h), _r(box[2] / w), _r(box[3] / h)]
    return {"crop": crop, "aspect": w / h, "words": [], "text_layer": False}


def read_page_layout(stored_path: str, file_type: str, page: int) -> dict | None:
    """One page's layout (1-based page), or None when the file or page is gone. PDFs are parsed in the render
    child (cached like page renders); images are decoded here under `compress.image_decode_slot`."""
    import json
    from pathlib import Path

    from app.services.accounting.render_pool import render_page

    path = Path(stored_path)
    if not path.is_file():
        return None
    if file_type == "pdf":
        data = render_page(str(path), page - 1, "layout")
        return json.loads(data) if data else None
    if page != 1:
        return None
    try:
        return image_layout(path.read_bytes())
    except (OSError, ValueError, Image.DecompressionBombError):
        return None
