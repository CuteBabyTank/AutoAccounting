"""Trim the blank margins around a page for the viewer (pure): a small receipt scanned on a full sheet shows as the
receipt, not as a speck on white. Only the image the browser shows is trimmed; the stored file is untouched.

PDF pages are re-rendered from the clipped region at a higher resolution, so the receipt comes out sharp when zoomed.
"""

import io

import fitz
from PIL import Image, ImageFilter

_PROBE_DPI = 36
_INK = 40               # how much darker than the paper a pixel must be to count as content
_KEEP_RATIO = 0.85      # don't bother when the content already covers most of the page
_PAD = 0.03             # margin kept around the content, as a share of its longer side
_TARGET_PIXELS = (130 / 72) ** 2 * 612 * 792   # about a Letter page at the viewer's 130 dpi
_MAX_DPI = 300


def content_box(img: Image.Image) -> tuple[int, int, int, int] | None:
    """(left, top, right, bottom) of what's printed on a light background, padded; None when there's nothing worth
    trimming (no margin, a dark or busy background such as a photo on a table, or a blank page)."""
    gray = img.convert("L")
    w, h = gray.size
    if w < 8 or h < 8:
        return None
    # The paper's colour is the brightest common tone; a speck of dust shouldn't stretch the box, hence the filter.
    hist = gray.resize((min(w, 64), min(h, 64))).histogram()
    paper, seen = 255, 0
    while paper > 0 and seen + hist[paper] < sum(hist) / 10:   # the tone 10% of the page is at least as light as
        seen += hist[paper]
        paper -= 1
    if paper < 180:
        return None
    mask = gray.filter(ImageFilter.MedianFilter(3)).point(lambda v: 255 if v < paper - _INK else 0)
    box = mask.getbbox()
    if box is None:
        return None
    left, top, right, bottom = box
    pad = int(max(right - left, bottom - top) * _PAD) + 2
    left, top, right, bottom = max(0, left - pad), max(0, top - pad), min(w, right + pad), min(h, bottom + pad)
    if (right - left) * (bottom - top) > _KEEP_RATIO * w * h:
        return None
    return left, top, right, bottom


def trimmed_image(data: bytes) -> tuple[bytes, str] | None:
    """A photo / scan with its blank margins cut off, as (bytes, media type); None to show the original."""
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.load()
            box = content_box(img)
            if box is None:
                return None
            out = io.BytesIO()
            img.crop(box).convert("RGB").save(out, "WEBP", quality=85)
            return out.getvalue(), "image/webp"
    except (OSError, ValueError, Image.DecompressionBombError):
        return None


def render_pdf_page_trimmed(pdf_path: str, page_number: int) -> bytes | None:
    """A PDF page (0-indexed) clipped to its content and rendered sharper, as WebP; None when it has no margin to
    trim (the caller renders the whole page as before)."""
    with fitz.open(pdf_path) as doc:
        if page_number >= len(doc):
            return None
        page = doc[page_number]
        probe = page.get_pixmap(dpi=_PROBE_DPI)
        img = Image.frombytes("RGB" if probe.n < 4 else "RGBA", (probe.width, probe.height), probe.samples)
        box = content_box(img)
        if box is None:
            return None
        scale = 72 / _PROBE_DPI
        r = page.rect
        clip = fitz.Rect(r.x0 + box[0] * scale, r.y0 + box[1] * scale, r.x0 + box[2] * scale, r.y0 + box[3] * scale)
        clip &= r
        if clip.is_empty:
            return None
        dpi = min(_MAX_DPI, int(72 * (_TARGET_PIXELS / (clip.width * clip.height)) ** 0.5))
        pix = page.get_pixmap(dpi=max(130, dpi), clip=clip)
        out = io.BytesIO()
        Image.frombytes("RGB" if pix.n < 4 else "RGBA", (pix.width, pix.height), pix.samples).convert("RGB").save(
            out, "WEBP", quality=80)
        return out.getvalue()
