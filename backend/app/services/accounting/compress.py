"""Shrink an uploaded file before it is kept (tax records stay ≥ 5 years, so storage adds up).

Pages stay legible for people and for extraction: photos and scans are kept at about 200 dpi (a phone photo's long
side at most 2400 px) as JPEG quality 80, and PDFs are rewritten with their images downsampled the same way, fonts
subset and streams compressed (lossless images stay lossless). A file is only replaced when the result is smaller, still opens and has the same
number of pages. Digitally signed or encrypted PDFs are left exactly as uploaded (rewriting breaks a signature).
The upload's sha256 stays the original's, so dropping the same file again is still caught as a duplicate.
"""

import io
import logging
import os
from dataclasses import dataclass
from pathlib import Path

import pymupdf
from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

MAX_SIDE = 2400        # px, long side of a photo / scanned image file
TARGET_DPI = 200       # images inside PDFs above THRESHOLD_DPI are brought down to this
THRESHOLD_DPI = 240
JPEG_QUALITY = 80
MIN_SAVING = 0.05      # keep the original unless the new file is at least 5% smaller


@dataclass(frozen=True)
class Compressed:
    path: str
    file_type: str      # "pdf" | "jpg" | "png"
    size: int
    original_size: int


def _image_bytes(data: bytes) -> tuple[bytes, str] | None:
    """A photo / screenshot as a smaller JPEG (or PNG for few-colour images), orientation applied, metadata dropped."""
    with Image.open(io.BytesIO(data)) as img:
        img = ImageOps.exif_transpose(img)
        if img.mode in ("RGBA", "LA", "P"):
            rgba = img.convert("RGBA")
            flat = Image.new("RGB", rgba.size, (255, 255, 255))
            flat.paste(rgba, mask=rgba.getchannel("A"))
            img = flat
        elif img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        if max(img.size) > MAX_SIDE:
            img.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
        jpeg = io.BytesIO()
        img.save(jpeg, "JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
        # Screenshots of text with few colours are often smaller (and sharper) as PNG.
        if img.getcolors(256) is not None:
            png = io.BytesIO()
            img.save(png, "PNG", optimize=True)
            if png.tell() < jpeg.tell():
                return png.getvalue(), "png"
        return jpeg.getvalue(), "jpg"


def _rewrite_options():
    """Images above THRESHOLD_DPI resampled (bicubic, so 300 dpi can reach 200) to TARGET_DPI. Photos are re-saved
    as JPEG; lossless images (screenshots, logos with text) stay lossless; black-and-white fax scans are untouched.
    Nothing is replaced unless it comes out smaller."""
    m = pymupdf.mupdf
    opts = m.PdfImageRewriterOptions()
    for colour in ("color", "gray"):
        for kind, method in (("lossy", m.FZ_RECOMPRESS_JPEG), ("lossless", m.FZ_RECOMPRESS_LOSSLESS)):
            prefix = f"{colour}_{kind}_image_"
            setattr(opts, prefix + "recompress_method", method)
            setattr(opts, prefix + "recompress_quality", str(JPEG_QUALITY))
            setattr(opts, prefix + "subsample_method", m.FZ_SUBSAMPLE_BICUBIC)
            setattr(opts, prefix + "subsample_threshold", THRESHOLD_DPI)
            setattr(opts, prefix + "subsample_to", TARGET_DPI)
    opts.bitonal_image_recompress_method = m.FZ_RECOMPRESS_NEVER
    opts.recompress_when = m.FZ_RECOMPRESS_WHEN_SMALLER
    return opts


def _pdf_bytes(data: bytes) -> bytes | None:
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        if doc.needs_pass or doc.is_encrypted or doc.get_sigflags() > 0:
            return None  # signed (e-invoices) or locked: keep exactly what was uploaded
        pages = doc.page_count
        doc.rewrite_images(options=_rewrite_options())
        doc.subset_fonts()
        out = doc.tobytes(garbage=3, deflate=True, deflate_images=True, deflate_fonts=True, use_objstms=1)
    with pymupdf.open(stream=out, filetype="pdf") as check:
        if check.page_count != pages:
            return None
    return out


def compress_bytes(data: bytes, file_type: str) -> tuple[bytes, str] | None:
    """The smaller file and its type, or None to keep the original (not worth it, or it couldn't be done safely)."""
    try:
        result = _pdf_bytes(data) if file_type == "pdf" else _image_bytes(data)
    except Exception as e:  # a file we can't rewrite is still a valid upload: keep it as it came
        logger.warning("compress_skipped type=%s error=%s", file_type, type(e).__name__)
        return None
    if result is None:
        return None
    out, kind = (result, "pdf") if isinstance(result, bytes) else result
    if len(out) > len(data) * (1 - MIN_SAVING):
        return None
    return out, kind


_EXT = {"pdf": ".pdf", "jpg": ".jpg", "png": ".png"}


def compress_file(path: str, file_type: str) -> Compressed:
    """Compress a stored upload in place (a PNG may become a .jpg next to it). Blocking: run in an executor."""
    src = Path(path)
    data = src.read_bytes()
    result = compress_bytes(data, file_type)
    if result is None:
        return Compressed(path, file_type, len(data), len(data))
    out, kind = result
    dest = src.with_suffix(_EXT[kind])
    tmp = dest.with_name(dest.name + ".tmp")
    tmp.write_bytes(out)
    os.replace(tmp, dest)
    if dest != src:
        src.unlink(missing_ok=True)
    logger.info("compressed type=%s from=%d to=%d", kind, len(data), len(out))
    return Compressed(str(dest), kind, len(out), len(data))
