import io

import fitz
from PIL import Image

from app.services.accounting.page_layout import _pdf_layout_local, image_layout
from app.services.accounting.page_trim import pdf_clip


def _pdf(tmp_path, words=(("TOTAL 1,234.50", (400, 600)),), name="a.pdf", size=11):
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    for text, at in words:
        page.insert_text(at, text, fontsize=size)
    path = tmp_path / name
    doc.save(str(path))
    return str(path)


def test_pdf_layout_words_and_crop_match_trim(tmp_path):
    path = _pdf(tmp_path)
    out = _pdf_layout_local(path, 0)
    assert out["text_layer"] is True
    assert abs(out["aspect"] - 612 / 792) < 1e-6
    amount = next(w for w in out["words"] if w[4] == "1,234.50")
    assert 400 / 612 < amount[0] < 0.8 and abs(amount[3] - 600 / 792) < 0.01
    with fitz.open(path) as doc:
        page = doc[0]
        clip = pdf_clip(page)
        r = page.rect
    assert clip is not None   # a few words on a blank Letter page: the viewer trims it
    want = [(clip.x0 - r.x0) / r.width, (clip.y0 - r.y0) / r.height, (clip.x1 - r.x0) / r.width,
            (clip.y1 - r.y0) / r.height]
    assert out["crop"] == [round(v, 5) for v in want]


def test_layout_caps_words(tmp_path):
    lines = [(" ".join("a" for _ in range(60)), (10, 10 + j * 6)) for j in range(125)]   # 7,500 words
    out = _pdf_layout_local(_pdf(tmp_path, lines, size=4), 0)
    assert out["words"] == [] and out["text_layer"] is False


def test_image_layout_has_no_words_and_full_crop_for_a_photo_without_margin():
    img = Image.new("RGB", (400, 300), (40, 40, 40))
    buf = io.BytesIO()
    img.save(buf, "JPEG")
    assert image_layout(buf.getvalue()) == {"crop": [0, 0, 1, 1], "aspect": 400 / 300, "words": [], "text_layer": False}


def test_image_layout_refuses_an_exif_rotated_photo():
    img = Image.new("RGB", (400, 300), (40, 40, 40))
    exif = img.getexif()
    exif[0x0112] = 6   # rotate 90: browser and reader might not agree on which way is up
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif.tobytes())
    assert image_layout(buf.getvalue())["crop"] is None


async def test_layout_route_is_firm_scoped_and_404s_a_foreign_file(monkeypatch):
    import uuid
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    import pytest
    from fastapi import HTTPException

    from app.routers import accounting

    seen = []

    async def execute(stmt):
        seen.append(str(stmt.compile(compile_kwargs={"literal_binds": False})))
        return SimpleNamespace(scalar_one_or_none=lambda: None)   # RLS / the filter found nothing

    ent = uuid.uuid4()
    monkeypatch.setattr(accounting, "_scope", lambda user: ent)
    with pytest.raises(HTTPException) as error:
        await accounting.file_page_layout(uuid.uuid4(), 1, SimpleNamespace(id=uuid.uuid4()),
                                          SimpleNamespace(execute=AsyncMock(side_effect=execute)))
    assert error.value.status_code == 404
    assert "enterprise_id" in seen[0]
