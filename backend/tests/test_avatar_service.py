import io

import pytest
from PIL import Image

from app.services.avatar_service import MAX_STORED_BYTES, SIDE, make_avatar


def _encode(img: Image.Image, fmt: str) -> bytes:
    out = io.BytesIO()
    img.save(out, fmt)
    return out.getvalue()


def test_photo_becomes_small_square_webp():
    photo = Image.effect_noise((3000, 2000), 60).convert("RGB")
    out = make_avatar(_encode(photo, "JPEG"))
    assert len(out) <= MAX_STORED_BYTES
    with Image.open(io.BytesIO(out)) as img:
        assert img.format == "WEBP"
        assert img.size == (SIDE, SIDE)


def test_transparent_png_is_flattened():
    png = Image.new("RGBA", (400, 800), (0, 0, 0, 0))
    with Image.open(io.BytesIO(make_avatar(_encode(png, "PNG")))) as img:
        assert img.mode == "RGB"
        assert img.getpixel((SIDE // 2, SIDE // 2)) > (240, 240, 240)


@pytest.mark.parametrize("data", [b"not an image", _encode(Image.new("RGB", (10, 10)), "GIF"), b"\xff" * (5 * 1024 * 1024 + 1)])
def test_rejects_non_jpeg_png_and_oversize(data):
    with pytest.raises(ValueError):
        make_avatar(data)
