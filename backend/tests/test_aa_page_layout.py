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


def test_rotated_pdf_words_are_in_the_shown_orientation(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((400, 600), "TOTAL 1,234.50", fontsize=11)
    page.set_rotation(90)
    path = tmp_path / "r.pdf"
    doc.save(str(path))
    out = _pdf_layout_local(str(path), 0)
    w = next(x for x in out["words"] if x[4] == "1,234.50")
    cx, cy = (w[0] + w[2]) / 2, (w[1] + w[3]) / 2
    x0, y0, x1, y1 = out["crop"]
    assert x0 <= cx <= x1 and y0 <= cy <= y1          # the word sits inside the trimmed region the viewer shows
    assert abs(out["aspect"] - 792 / 612) < 1e-6      # landscape as shown


def test_scanned_pdf_with_a_stray_text_line_goes_to_ocr(tmp_path):
    import io as _io

    from PIL import Image as _Image

    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    img = _Image.new("RGB", (600, 780), (230, 230, 230))
    buf = _io.BytesIO()
    img.save(buf, "PNG")
    page.insert_image(fitz.Rect(6, 6, 606, 786), stream=buf.getvalue())
    page.insert_text((20, 780), "Scanned with CamScanner", fontsize=6)
    path = tmp_path / "s.pdf"
    doc.save(str(path))
    out = _pdf_layout_local(str(path), 0)
    assert out["text_layer"] is False and out["words"] == []


def test_a_trimmed_page_render_also_caches_its_layout(tmp_path, monkeypatch):
    import json
    import subprocess

    from app.services.accounting import render_pool

    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((200, 300), "INVOICE 0071420", fontsize=12)
    path = tmp_path / "t.pdf"
    doc.save(str(path))
    render_pool._CACHE.clear()
    calls = []
    real = subprocess.run
    monkeypatch.setattr(render_pool.subprocess, "run", lambda *a, **k: calls.append(a[0][10]) or real(*a, **k))
    assert render_pool.render_page(str(path), 0, "trimmed")
    layout = json.loads(render_pool.render_page(str(path), 0, "layout"))
    assert calls == ["trimmed"]                       # one child for both
    assert layout == _pdf_layout_local(str(path), 0)  # the same layout the layout route would compute
