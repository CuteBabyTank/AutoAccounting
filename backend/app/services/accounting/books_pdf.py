"""Loose-leaf books of accounts as PDFs: 8.5" × 13" (long bond) landscape pages, numbered per book per fiscal year.

Each page carries the registered name, TIN-branch, address, book title, the month and the page number. Columnar
journals show the column totals brought forward from the previous page and carried forward to the next, and the
month's totals on the last page. Binding a year adds a cover and the sworn declaration (RR 9-2009 / RMO 29-2002
loose-leaf practice).
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import fitz

from app.services.accounting.compute.money import ZERO, c2
from app.services.accounting.compute.specs import LEDGER_COLUMNS, LEDGER_TITLES

PAGE = fitz.Rect(0, 0, 936, 612)        # 13" × 8.5", landscape
MARGIN = 28
FONT, BOLD = "helv", "hebo"
SIZE = 6.8
ROW = 10.5
_JOURNALS = ("SJ", "PJ", "CRJ", "CDJ")   # columnar: brought / carried forward totals


@dataclass(frozen=True)
class Header:
    name: str
    tin: str                 # 123-456-789-00000
    address: str
    rdo: str = ""


def _text(value) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, Decimal):
        return f"{value:,.2f}" if value else ""
    return str(value)


def _fit(text: str, width: float, font: str = FONT, size: float = SIZE) -> str:
    if fitz.get_text_length(text, fontname=font, fontsize=size) <= width:
        return text
    while text and fitz.get_text_length(text + "...", fontname=font, fontsize=size) > width:
        text = text[:-1]
    return text + "..."


def _widths(columns, usable: float) -> list[float]:
    money = [c for c in columns if c[2] == "money"]
    fixed = {"date": 46, "entry_no": 64, "reference": 64, "tin": 62, "code": 40, "side": 22}
    taken = 62 * len(money) + sum(fixed.get(c[0], 0) for c in columns if c[2] != "money")
    flexible = [c for c in columns if c[2] != "money" and c[0] not in fixed]
    share = max((usable - taken) / max(len(flexible), 1), 50)
    return [62 if c[2] == "money" else fixed.get(c[0], share) for c in columns]


def _header(page, header: Header, title: str, period: str, number: int) -> float:
    y = MARGIN
    page.insert_text((MARGIN, y), header.name.upper(), fontname=BOLD, fontsize=10)
    page.insert_text((PAGE.width - MARGIN - 70, y), f"Page {number}", fontname=BOLD, fontsize=9)
    y += 12
    page.insert_text((MARGIN, y), _fit(f"TIN {header.tin}   ·   {header.address}", PAGE.width - 2 * MARGIN, size=7.5),
                     fontname=FONT, fontsize=7.5)
    y += 14
    page.insert_text((MARGIN, y), title.upper(), fontname=BOLD, fontsize=9.5)
    page.insert_text((MARGIN + 260, y), period, fontname=FONT, fontsize=8.5)
    return y + 10


def _row(page, y: float, xs: list[float], widths: list[float], columns, values: list[str], bold=False,
         label: str = "") -> None:
    """``label`` (totals rows) spans the text columns before the first amount column."""
    font = BOLD if bold else FONT
    if label:
        first_money = next((i for i, c in enumerate(columns) if c[2] == "money"), len(columns))
        span = sum(widths[:first_money]) or widths[0]
        page.insert_text((xs[0] + 2, y), _fit(label, span - 4, font), fontname=font, fontsize=SIZE)
    for (key, _, kind), x, w, value in zip(columns, xs, widths, values):
        if label and kind != "money":
            continue
        text = _fit(value, w - 4, font)
        if kind == "money":
            tw = fitz.get_text_length(text, fontname=font, fontsize=SIZE)
            page.insert_text((x + w - 2 - tw, y), text, fontname=font, fontsize=SIZE)
        else:
            page.insert_text((x + 2, y), text, fontname=font, fontsize=SIZE)


def render_book(doc: fitz.Document, book: str, rows: list[dict], header: Header, period: str,
                first_page: int) -> int:
    """Append the book's pages for one month to ``doc``; returns how many pages were added (at least one)."""
    columns = [c for c in LEDGER_COLUMNS[book]]
    usable = PAGE.width - 2 * MARGIN
    widths = _widths(columns, usable)
    scale = usable / sum(widths)
    widths = [w * scale for w in widths]
    xs, x = [], MARGIN
    for w in widths:
        xs.append(x)
        x += w
    money = [i for i, c in enumerate(columns) if c[2] == "money" and c[0] not in ("balance",)]
    columnar = book in _JOURNALS or book == "GJ"
    running = [ZERO] * len(columns)
    title = LEDGER_TITLES.get(book, book)
    pages = 0
    index = 0
    bottom = PAGE.height - MARGIN - (2 * ROW if columnar else ROW)
    while True:
        page = doc.new_page(width=PAGE.width, height=PAGE.height)
        pages += 1
        y = _header(page, header, title, period, first_page + pages - 1) + 4
        _row(page, y, xs, widths, columns, [c[1] for c in columns], bold=True)
        page.draw_line((MARGIN, y + 3), (PAGE.width - MARGIN, y + 3), width=0.6)
        y += ROW + 2
        if columnar and pages > 1:
            _row(page, y, xs, widths, columns,
                 [_text(c2(running[i])) if i in money else "" for i in range(len(columns))], bold=True,
                 label="Brought forward")
            y += ROW
        while index < len(rows) and y <= bottom:
            r = rows[index]
            _row(page, y, xs, widths, columns, [_text(r.get(c[0], "")) for c in columns])
            for i in money:
                value = r.get(columns[i][0])
                if isinstance(value, Decimal):
                    running[i] += value
            y += ROW
            index += 1
        if not rows and pages == 1:
            page.insert_text((MARGIN + 2, y), "No transactions this month.", fontname=FONT, fontsize=SIZE)
            y += ROW
        if columnar:
            page.draw_line((MARGIN, y - 7), (PAGE.width - MARGIN, y - 7), width=0.4)
            last = index >= len(rows)
            _row(page, y, xs, widths, columns,
                 [_text(c2(running[i])) if i in money else "" for i in range(len(columns))], bold=True,
                 label="Totals for the month" if last else "Carried forward")
        if index >= len(rows):
            return pages


def cover_page(doc: fitz.Document, header: Header, book: str, fiscal_year: int, start: date, end: date,
               volume: int = 1) -> None:
    page = doc.new_page(width=PAGE.width, height=PAGE.height)
    title = LEDGER_TITLES.get(book, book).upper()
    lines = [(header.name.upper(), BOLD, 18), (f"TIN {header.tin}", FONT, 11), (header.address, FONT, 10)]
    if header.rdo:
        lines.append((f"RDO {header.rdo}", FONT, 10))
    lines += [("", FONT, 10), (title, BOLD, 22), (f"Fiscal year {fiscal_year}", FONT, 12),
              (f"{start:%B %-d, %Y} to {end:%B %-d, %Y}", FONT, 11), (f"Volume {volume}", FONT, 11)]
    y = 150
    for text, font, size in lines:
        width = fitz.get_text_length(text, fontname=font, fontsize=size)
        page.insert_text(((PAGE.width - width) / 2, y), text, fontname=font, fontsize=size)
        y += size + 12
    box = fitz.Rect(PAGE.width - MARGIN - 190, PAGE.height - MARGIN - 130, PAGE.width - MARGIN, PAGE.height - MARGIN)
    page.draw_rect(box, width=0.6)
    page.insert_text((box.x0 + 6, box.y0 + 12), "BIR stamp / ORUS QR code", fontname=FONT, fontsize=7.5)


def sworn_declaration(doc: fitz.Document, header: Header, books: list[tuple[str, int]], fiscal_year: int,
                      start: date, end: date, signatory: str, signatory_title: str) -> None:
    """The declaration filed with the bound loose-leaf books: pages and volumes used per book."""
    page = doc.new_page(width=PAGE.width, height=PAGE.height)
    y = MARGIN + 30
    title = "SWORN DECLARATION"
    page.insert_text(((PAGE.width - fitz.get_text_length(title, fontname=BOLD, fontsize=14)) / 2, y), title,
                     fontname=BOLD, fontsize=14)
    y += 30
    body = (f"I, {signatory or '______________________________'}, {signatory_title or '__________________'} of "
            f"{header.name}, with TIN {header.tin} and address at {header.address}, after having been duly sworn in "
            "accordance with law, declare that the loose-leaf books of accounts listed below were used to record the "
            f"transactions for the fiscal year {fiscal_year} ({start:%B %-d, %Y} to {end:%B %-d, %Y}), and that the "
            "number of pages and volumes used are as stated:")
    rect = fitz.Rect(MARGIN + 40, y, PAGE.width - MARGIN - 40, y + 70)
    page.insert_textbox(rect, body, fontname=FONT, fontsize=10)
    y += 80
    page.insert_text((MARGIN + 60, y), "Book of accounts", fontname=BOLD, fontsize=10)
    page.insert_text((MARGIN + 420, y), "Pages", fontname=BOLD, fontsize=10)
    page.insert_text((MARGIN + 520, y), "Volumes", fontname=BOLD, fontsize=10)
    for book, count in books:
        y += 16
        page.insert_text((MARGIN + 60, y), LEDGER_TITLES.get(book, book), fontname=FONT, fontsize=10)
        page.insert_text((MARGIN + 420, y), str(count), fontname=FONT, fontsize=10)
        page.insert_text((MARGIN + 520, y), "1", fontname=FONT, fontsize=10)
    y += 50
    page.insert_text((PAGE.width - MARGIN - 300, y), "_______________________________", fontname=FONT, fontsize=10)
    page.insert_text((PAGE.width - MARGIN - 300, y + 14), signatory or "Signature over printed name",
                     fontname=FONT, fontsize=9)
    page.insert_text((PAGE.width - MARGIN - 300, y + 26), signatory_title, fontname=FONT, fontsize=9)
    y += 60
    page.insert_textbox(fitz.Rect(MARGIN + 40, y, PAGE.width - MARGIN - 40, y + 60),
                        "SUBSCRIBED AND SWORN to before me this ____ day of ______________, 20___, affiant exhibiting "
                        "competent evidence of identity ____________________.\n\nDoc. No. ____; Page No. ____; "
                        "Book No. ____; Series of ____.", fontname=FONT, fontsize=9)


def month_pdf(book: str, rows: list[dict], header: Header, period: str, first_page: int) -> tuple[bytes, int]:
    doc = fitz.open()
    count = render_book(doc, book, rows, header, period, first_page)
    return doc.tobytes(garbage=3, deflate=True), count
