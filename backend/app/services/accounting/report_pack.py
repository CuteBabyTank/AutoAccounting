"""Quarterly management report pack: cover, contents, P&L, Balance Sheet, cash flow, A/R and A/P aging, key ratios
and the preparer's notes, as PDF (PyMuPDF) and DOCX (zipfile + minimal WordprocessingML, no extra dependency)."""

import io
import re
import zipfile
from dataclasses import dataclass
from decimal import Decimal
from xml.sax.saxutils import escape

from app.services.accounting.books_pdf import MARGIN, Header
from app.services.accounting.compute.subledger import BUCKET_LABELS, BUCKETS
from app.services.accounting.report_export import layout, pdf_text, table_for
from app.services.accounting.subledger_report import _PORTRAIT, _cut, _header, _Writer, peso

SECTION_TITLES = ("Profit and loss", "Balance sheet", "Cash flow", "Accounts receivable aging",
                  "Accounts payable aging", "Key ratios", "Notes")
_CONTROL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")  # not allowed in XML 1.0


@dataclass
class Pack:
    header: Header
    period: str                       # "Q4 2026 (Oct–Dec)"
    prepared: str                     # date text
    pnl: dict                         # compute.reports.profit_and_loss (quarter, fiscal year to date)
    bs: dict                          # compute.reports.balance_sheet (+ with_change)
    cash_flow: list[dict]             # compute.reports.cash_flow rows
    aging: dict                       # {"ar" | "ap": ([(name, tin, buckets incl. total)], totals)}
    kpis: dict | None
    notes: str


def _ratio(value, pct: bool) -> str:
    if value is None:
        return "n/a"
    return f"{value:,.2f}%" if pct else f"{value:,.2f}"


def sections(pack: Pack) -> list[tuple[str, list[str], list[dict]]]:
    """(title, heads, rows) per section, rows as in ``report_export.table_for``."""
    out = []
    out.append((SECTION_TITLES[0], *table_for("pnl", pack.pnl)))
    out.append((SECTION_TITLES[1], *table_for("balance-sheet", pack.bs)))
    cf = [{"cells": [("  " * r.get("level", 0)) + r["line"], "" if r["amount"] is None else r["amount"]],
           "bold": r.get("level", 0) == 0} for r in pack.cash_flow]
    out.append((SECTION_TITLES[2], ["", "Amount"], cf))
    for kind, title in (("ar", SECTION_TITLES[3]), ("ap", SECTION_TITLES[4])):
        rows, totals = pack.aging[kind]
        heads = ["Customer" if kind == "ar" else "Supplier"] + [BUCKET_LABELS[b] for b in BUCKETS] + ["Total"]
        body = [{"cells": [name] + [buckets[b] for b in BUCKETS] + [buckets["total"]], "bold": False}
                for name, _, buckets in rows]
        body.append({"cells": ["Total"] + [totals[b] for b in BUCKETS] + [totals["total"]], "bold": True})
        out.append((title, heads, body))
    k = pack.kpis
    ratios = [] if k is None else [
        ("Net sales", peso(k["net_sales"])), ("Gross margin", _ratio(k["gross_margin"], True)),
        ("Net margin", _ratio(k["net_margin"], True)), ("Operating expenses to sales", _ratio(k["opex_ratio"], True)),
        ("Current ratio", _ratio(k["current_ratio"], False)), ("Quick ratio", _ratio(k["quick_ratio"], False))]
    out.append((SECTION_TITLES[5], ["Measure", "Value"],
                [{"cells": [a, b], "bold": False} for a, b in ratios]
                or [{"cells": ["The books couldn't be built for this quarter.", ""], "bold": False}]))
    notes = clean(pack.notes) or "No notes."
    out.append((SECTION_TITLES[6], [], [{"cells": [line], "bold": False} for line in notes.split("\n")]))
    return out


def clean(text: str) -> str:
    return _CONTROL.sub("", text or "").replace("\r\n", "\n").strip()


# --- PDF -------------------------------------------------------------------------------------------------------------

def _wrap(text: str, width: float, size: float = 9) -> list[str]:
    import fitz

    lines, line = [], ""
    for word in text.split(" "):
        candidate = f"{line} {word}".strip()
        if fitz.get_text_length(pdf_text(candidate), fontname="helv", fontsize=size) <= width or not line:
            line = candidate
        else:
            lines.append(line)
            line = word
    return lines + [line]


def pack_pdf(pack: Pack) -> bytes:
    w = _Writer(_PORTRAIT)
    page_width = _PORTRAIT.width - 2 * MARGIN
    w.y = 260
    w.text(pdf_text(pack.header.name.upper()), bold=True, size=18)
    w.gap(8)
    w.text("MANAGEMENT REPORT", bold=True, size=14)
    w.text(pdf_text(pack.period), size=12)
    w.gap(20)
    w.text(f"TIN {pack.header.tin}", size=9)
    if pack.header.address:
        w.text(pdf_text(pack.header.address), size=9)
    w.text(f"Prepared {pack.prepared} · accrual basis, from the books of accounts", size=9)
    starts: list[int] = []
    for title, heads, rows in sections(pack):
        w.new_page()
        starts.append(len(w.doc) + 1)  # page number once the contents page is inserted at index 1
        _header(w, pack.header, title.upper(), pdf_text(pack.period))
        if not heads:  # notes: wrapped paragraphs
            for r in rows:
                for line in _wrap(r["cells"][0], page_width):
                    w.text(pdf_text(line))
            continue
        cols = layout(heads, rows, page_width)

        def line(cells, bold):
            w.row([(x, _cut(pdf_text(c), width) if align == "l" else pdf_text(c), align)
                   for (x, width, align), c in zip(cols, cells)], bold=bold)

        line(heads, True)
        for r in rows:
            if w.y > w.rect.height - MARGIN - 13:
                w.new_page()
                line(heads, True)
            line(r["cells"], r["bold"])
    contents = w.doc.new_page(pno=1, width=_PORTRAIT.width, height=_PORTRAIT.height)
    y = MARGIN + 30
    contents.insert_text((MARGIN, y), "CONTENTS", fontname="hebo", fontsize=14)
    for title, page in zip(SECTION_TITLES, starts):
        y += 20
        contents.insert_text((MARGIN, y), title, fontname="helv", fontsize=11)
        label = str(page)
        contents.insert_text((MARGIN + page_width - len(label) * 6, y), label, fontname="helv", fontsize=11)
    return w.bytes()


# --- DOCX ------------------------------------------------------------------------------------------------------------

_W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
_CONTENT_TYPES = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                  '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                  '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                  '<Default Extension="xml" ContentType="application/xml"/>'
                  '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.'
                  'wordprocessingml.document.main+xml"/></Types>')
_RELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
         '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
         '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
         'officeDocument" Target="word/document.xml"/></Relationships>')


def _x(text) -> str:
    return escape(clean(str(text)) if isinstance(text, str) else str(text))


def _run(text, *, bold: bool = False, size: int | None = None) -> str:
    props = ("<w:b/>" if bold else "") + (f'<w:sz w:val="{size * 2}"/>' if size else "")
    return (f"<w:r>{f'<w:rPr>{props}</w:rPr>' if props else ''}"
            f'<w:t xml:space="preserve">{_x(text)}</w:t></w:r>')


def _para(text="", *, bold=False, size=None, right=False, page_break=False) -> str:
    ppr = '<w:pPr><w:jc w:val="right"/></w:pPr>' if right else ""
    brk = '<w:r><w:br w:type="page"/></w:r>' if page_break else ""
    return f"<w:p>{ppr}{brk}{_run(text, bold=bold, size=size) if text != '' else ''}</w:p>"


def _cell_text(value) -> tuple[str, bool]:
    if isinstance(value, Decimal):
        return peso(value), True
    return ("" if value is None else str(value)), False


def _table(heads: list[str], rows: list[dict]) -> str:
    border = "".join(f'<w:{s} w:val="single" w:sz="4" w:space="0" w:color="BBBBBB"/>'
                     for s in ("top", "left", "bottom", "right", "insideH", "insideV"))
    grid = "".join('<w:gridCol w:w="{}"/>'.format(9360 // max(len(heads), 1)) for _ in heads)  # required by CT_Tbl
    out = [f'<w:tbl><w:tblPr><w:tblW w:w="5000" w:type="pct"/><w:tblBorders>{border}</w:tblBorders></w:tblPr>'
           f'<w:tblGrid>{grid}</w:tblGrid>']
    for cells, bold in [(heads, True)] + [(r["cells"], r["bold"]) for r in rows]:
        out.append("<w:tr>")
        for value in cells:
            text, right = _cell_text(value)
            out.append(f"<w:tc>{_para(text, bold=bold, size=9, right=right)}</w:tc>")
        out.append("</w:tr>")
    out.append("</w:tbl>")
    return "".join(out)


def pack_docx(pack: Pack) -> bytes:
    body = [_para(pack.header.name, bold=True, size=20), _para("Management report", bold=True, size=16),
            _para(pack.period, size=13), _para(f"TIN {pack.header.tin}"), _para(pack.header.address),
            _para(f"Prepared {pack.prepared} · accrual basis, from the books of accounts"),
            _para("Contents", bold=True, size=14, page_break=True)]
    body += [_para(f"{n}. {title}") for n, title in enumerate(SECTION_TITLES, start=1)]
    for title, heads, rows in sections(pack):
        body.append(_para(title, bold=True, size=14, page_break=True))
        body.append(_para(pack.period, size=10))
        if heads:
            body.append(_table(heads, rows))
        else:
            body += [_para(r["cells"][0]) for r in rows]
    document = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {_W}><w:body>'
                + "".join(body) + '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/></w:sectPr></w:body></w:document>')
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CONTENT_TYPES)
        z.writestr("_rels/.rels", _RELS)
        z.writestr("word/document.xml", document)
    return out.getvalue()
