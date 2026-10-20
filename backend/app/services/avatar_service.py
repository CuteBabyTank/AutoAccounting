"""Profile pictures: a JPEG / PNG upload becomes a small square WebP kept on the user row.

The sidebar shows it at 33 px, so 192 px covers a 3x screen with room to spare and the stored file is
usually 5–15 KB. EXIF orientation is applied and all metadata (GPS included) is dropped.
"""

import io

from PIL import Image, ImageOps

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_PIXELS = 50_000_000   # refuse decompression bombs before decoding
SIDE = 192                # px, stored square
QUALITY = 78
MAX_STORED_BYTES = 60 * 1024


def make_avatar(data: bytes) -> bytes:
    """The upload as a center-cropped SIDE×SIDE WebP. Raises ValueError for anything that isn't a JPEG / PNG."""
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("Image must be under 5 MB.")
    try:
        with Image.open(io.BytesIO(data)) as img:
            if img.format not in ("JPEG", "PNG"):
                raise ValueError("Upload a JPG or PNG image.")
            if img.width * img.height > MAX_PIXELS:
                raise ValueError("Image is too large.")
            img = ImageOps.exif_transpose(img)
            if img.mode in ("RGBA", "LA", "P"):
                rgba = img.convert("RGBA")
                flat = Image.new("RGB", rgba.size, (255, 255, 255))
                flat.paste(rgba, mask=rgba.getchannel("A"))
                img = flat
            elif img.mode != "RGB":
                img = img.convert("RGB")
            img = ImageOps.fit(img, (SIDE, SIDE), Image.Resampling.LANCZOS)
    except ValueError:
        raise
    except Exception as exc:  # truncated / corrupt files, Pillow's DecompressionBombError
        raise ValueError("That file couldn't be read as an image.") from exc
    quality = QUALITY
    while True:
        out = io.BytesIO()
        img.save(out, "WEBP", quality=quality, method=6)
        if out.tell() <= MAX_STORED_BYTES or quality <= 40:
            return out.getvalue()
        quality -= 10
