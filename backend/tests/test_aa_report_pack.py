"""Management report pack: PDF (cover, contents, statements, aging, KPIs, notes) and DOCX."""

import asyncio
import io
import uuid
import zipfile
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import fitz
import pytest
from fastapi import HTTPException

from app.models.accounting import AAPeriod
from app.services.accounting.books.chart import Chart, standard_chart
from app.services.accounting.books_pdf import Header
from app.services.accounting.compute.books import Entry, Line
from app.services.accounting.compute.reports import balance_sheet, cash_flow, columns_for, kpis, profit_and_loss
from app.services.accounting.compute.subledger import BUCKETS
from app.services.accounting.report_pack import SECTION_TITLES, Pack, pack_docx, pack_pdf
from app.services.accounting.schema import column_statements

D = Decimal
CHART = Chart(standard_chart("corporation"))
ENTRIES = [
    Entry("je:o", date(2026, 1, 1), "GJ", "OB", "", "", "Opening", "opening",
          (Line("1010", D("100000")), Line("3010", credit=D("100000")))),
    Entry("doc:s:sale", date(2026, 11, 5), "SJ", "0006", "Kalayaan", "", "Sale", "document",
          (Line("1100", D("11200")), Line("4010", credit=D("10000")), Line("2100", credit=D("1200")))),
]


def test_pack_generation_is_limited_before_loading_books(monkeypatch):
    from app.auth.security import RateLimiter
    from app.routers import accounting_reports as routes

    user = SimpleNamespace(id=uuid.uuid4())
    limiter = RateLimiter(1, 600)
    limiter.check_and_record(str(user.id))
    monkeypatch.setattr(routes, "export_limiter", limiter)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(routes.generate_pack("company", 2026, 4, user=user, db=None))
    assert exc.value.status_code == 429

    async def load_books(*args):
        raise ValueError("another user can load books")

    monkeypatch.setattr(routes, "_pack_period", load_books)
    with pytest.raises(ValueError, match="another user can load books"):
        asyncio.run(routes.generate_pack("company", 2026, 4, user=SimpleNamespace(id=uuid.uuid4()), db=None))


def test_superseded_pack_cleanup_stays_inside_storage(tmp_path, monkeypatch):
    from app.config import settings
    from app.routers.accounting_reports import _delete_pack_files

    root = tmp_path / "storage"
    root.mkdir()
    monkeypatch.setattr(settings, "accounting_dir", str(root))
    inside, outside = root / "old.pdf", tmp_path / "outside.docx"
    inside.write_bytes(b"old")
    outside.write_bytes(b"keep")
    link = root / "link.docx"
    link.symlink_to(outside)
    _delete_pack_files({"pdf": str(inside), "docx": str(link), "by": str(outside)})
    assert not inside.exists()
    assert outside.read_bytes() == b"keep" and link.is_symlink()
    _delete_pack_files({"pdf": str(root / ".." / "outside.docx"), "docx": str(inside)})
    assert outside.exists()  # traversal and already-missing paths are safe


def _pack(notes: str = "Sales rose in November.\nAsk the client for the Oct–Nov bank statement <soon> & more.") -> Pack:
    q = columns_for(date(2026, 10, 1), date(2026, 12, 31), "total", 12)
    pnl = profit_and_loss(ENTRIES, CHART, q)
    bs = balance_sheet(ENTRIES, CHART, [date(2026, 12, 31), date(2026, 9, 30)], 12, "3020")
    zero = {b: D("0.00") for b in BUCKETS} | {"total": D("0.00")}
    return Pack(
        header=Header("Bayanihan Hardware Trading Corp.", "123-456-789-00000", "Marikina"),
        period="Q4 2026 (Oct–Dec)", prepared="2026-10-17", pnl=pnl, bs=bs,
        cash_flow=cash_flow(ENTRIES, CHART, date(2026, 10, 1), date(2026, 12, 31), 12, "3020"),
        aging={"ar": ([("Kalayaan", "", {**zero, "current": D("11200.00"), "total": D("11200.00")})],
                      {**zero, "current": D("11200.00"), "total": D("11200.00")}), "ap": ([], zero)},
        kpis=kpis(pnl, bs, CHART), notes=notes)


def test_pack_pdf_sections_in_order():
    doc = fitz.open(stream=pack_pdf(_pack()), filetype="pdf")
    text = "\n".join(page.get_text() for page in doc)
    assert "MANAGEMENT REPORT" in doc[0].get_text() and "Q4 2026" in doc[0].get_text()
    assert "CONTENTS" in doc[1].get_text()
    body = "\n".join(page.get_text() for page in doc[2:])
    positions = [body.index(t.upper()) for t in SECTION_TITLES]
    assert positions == sorted(positions)
    assert all(t in doc[1].get_text() for t in SECTION_TITLES)
    assert "Ask the client for the Oct–Nov bank statement" in text or "Ask the client for the Oct" in text


def test_pack_docx_is_valid_and_escapes_notes():
    data = pack_docx(_pack())
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = set(z.namelist())
        assert {"[Content_Types].xml", "_rels/.rels", "word/document.xml"} <= names
        xml = z.read("word/document.xml").decode()
    assert "&lt;soon&gt; &amp; more" in xml
    for title in SECTION_TITLES:
        assert title in xml
    assert "Kalayaan" in xml and "11,200.00" in xml


def test_pack_docx_strips_control_characters():
    xml = zipfile.ZipFile(io.BytesIO(pack_docx(_pack("bad\x00\x07 note")))).read("word/document.xml").decode()
    assert "bad note" in xml


def test_pack_columns():
    assert {"pack_notes", "pack_files"} <= set(AAPeriod.__table__.columns.keys())
    sql = "\n".join(column_statements())
    assert "ALTER TABLE aa_periods ADD COLUMN IF NOT EXISTS pack_notes TEXT NOT NULL DEFAULT ''" in sql
    assert "ALTER TABLE aa_periods ADD COLUMN IF NOT EXISTS pack_files JSONB NOT NULL DEFAULT '{}'::jsonb" in sql


def test_pack_docx_is_well_formed_with_odd_text_and_tables_have_grids():
    from xml.dom import minidom

    pack = _pack("note ￾￿ end")
    pack.header = Header("Ñoño & Sons <Trading> ￿", "123-456-789-00000", "")
    xml = zipfile.ZipFile(io.BytesIO(pack_docx(pack))).read("word/document.xml").decode()
    doc = minidom.parseString(xml.encode())  # raises on characters XML 1.0 forbids
    assert "Ñoño &amp; Sons &lt;Trading&gt;" in xml and "note  end" in xml
    for tbl in doc.getElementsByTagName("w:tbl"):  # CT_Tbl requires tblGrid after tblPr
        grid = tbl.getElementsByTagName("w:tblGrid")
        assert grid, "table without w:tblGrid"
        first_row = tbl.getElementsByTagName("w:tr")[0]
        assert len(grid[0].getElementsByTagName("w:gridCol")) == len(first_row.getElementsByTagName("w:tc"))
