"""Fill BIR Form 2550-Q from a version's stored values (PyMuPDF overlay on the official template)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import fitz  # PyMuPDF

from app.forms import bir2550q_layout as L
from app.services.accounting.pdf_overlay import _highlight, _write_amount, banner_text, draw_banner

BLACK = (0, 0, 0)


@dataclass(frozen=True)
class Header2550Q:
    tin: str
    rdo_code: str
    name: str
    address: str
    zip_code: str
    fiscal_year_end_month: int
    fiscal_year: int
    quarter: int
    period_from: date
    period_to: date
    branch_code: str = "00000"
    contact_number: str = ""
    email: str = ""
    classification: str = ""   # micro | small | medium | large


def _width(text: str, size: float) -> float:
    return fitz.get_text_length(text, fontname=L.FONT_NAME, fontsize=size)


def _centre(page, x: float, y: float, text: str, size: float) -> None:
    page.insert_text((x - _width(text, size) / 2, y), text, fontname=L.FONT_NAME, fontsize=size, color=BLACK)


def _cells(page, cells: tuple[list[float], float], text: str) -> None:
    centres, y = cells
    for x, char in zip(centres, text):
        if char.strip():
            _centre(page, x, y, char, L.CELL_FONT_SIZE)


def render_2550q(values: dict[str, str], header: Header2550Q, highlights: frozenset[str] = frozenset(),
                 amended: bool = False, draft_reviews: int = 0, missing: Sequence[str] = ()) -> bytes:
    doc = fitz.open(L.TEMPLATE_PATH)
    try:
        p1, p2 = doc[0], doc[1]
        _centre(p1, *(L.P1_CALENDAR if header.fiscal_year_end_month == 12 else L.P1_FISCAL), "X", 9)
        _cells(p1, L.P1_YEAR_ENDED, f"{header.fiscal_year_end_month:02d}{header.fiscal_year}")
        _centre(p1, *L.P1_QUARTER[header.quarter], "X", 9)
        _cells(p1, L.P1_PERIOD_FROM, header.period_from.strftime("%m%d%Y"))
        _cells(p1, L.P1_PERIOD_TO, header.period_to.strftime("%m%d%Y"))
        _centre(p1, *L.P1_AMENDED[amended], "X", 9)
        _centre(p1, *L.P1_SHORT_PERIOD_NO, "X", 9)
        _cells(p1, L.P1_TIN, header.tin[:9])
        branch = (header.branch_code or "00000")[:5]
        if branch != "00000":  # the template pre-prints the head office's 00000: replace it
            x0, x1 = L.P1_BRANCH_EDGES
            p1.add_redact_annot(fitz.Rect(x0 + 1, L.P1_TIN[1] - 9, x1 - 1, L.P1_TIN[1] + 4.5), fill=(1, 1, 1))
            p1.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=fitz.PDF_REDACT_LINE_ART_NONE)
            _cells(p1, (L.P1_BRANCH, L.P1_TIN[1]), branch)
        _cells(p1, L.P1_RDO, header.rdo_code[:3])
        _cells(p1, L.P1_NAME, header.name.upper())
        _cells(p1, L.P1_ADDRESS, header.address.upper())
        _cells(p1, L.P1_ZIP, header.zip_code[:4])
        _cells(p1, L.P1_CONTACT, header.contact_number)
        _cells(p1, L.P1_EMAIL, header.email)
        if header.classification in L.P1_CLASS:
            _centre(p1, *L.P1_CLASS[header.classification], "X", 9)
        _centre(p1, *L.P1_RELIEF_NO, "X", 9)
        _cells(p2, L.P2_TIN, header.tin[:9])
        _cells(p2, L.P2_NAME, header.name.upper())

        overflow: list[str] = []
        for key, spec in L.AMOUNTS.items():
            text = values.get(key, "")
            if not text:
                continue
            page = doc[spec.page]
            if key in highlights:
                _highlight(page, spec)
            if not _write_amount(page, spec, text):
                overflow.append(key)

        notes = ["Highlighted = changed since the previous version"] if highlights else []
        if overflow:
            notes.append("Too long for the boxes (printed in red): " + ", ".join(overflow))
        if notes:
            p1.insert_text(L.FOOTNOTE, " · ".join(notes), fontname=L.FONT_NAME, fontsize=7, color=BLACK)
        banner = banner_text(draft_reviews, missing)
        if banner:
            draw_banner(doc, L.DRAFT_BANNER, banner, 11)
        return doc.tobytes(garbage=3, deflate=True)
    finally:
        doc.close()
