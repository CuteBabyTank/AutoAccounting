"""BIR Form 2316 (September 2021 ENCS) filled over the official blank, one page per employee.

Positions are PDF points (origin top-left) measured from the template's boxes. Amounts are right-aligned in their
box with centavos; TINs, the year and dates go one character per printed cell.
"""

import hashlib
import io
import zipfile
from datetime import date
from decimal import Decimal
from pathlib import Path

import fitz

from app.services.accounting.compute.alphalist import Computed

TEMPLATE = Path(__file__).resolve().parents[2] / "forms" / "templates" / "bir2316_sep2021.pdf"
FONT, SIZE = "helv", 8.5

# Amount boxes: item → (x0, x1, baseline)
_RIGHT = {n: (483.8, 585.6, y) for n, y in (
    ("29", 152.0), ("30", 171.5), ("31", 191.3), ("32", 211.4), ("33", 231.5), ("34", 251.0), ("35", 270.0),
    ("36", 289.3), ("37", 308.5), ("38", 327.7), ("39", 365.5), ("40", 385.0), ("41", 404.0), ("42", 423.4),
    ("43", 442.5), ("44A", 470.0), ("45", 514.0), ("46", 533.0), ("47", 552.5), ("48", 572.0), ("49", 591.4),
    ("50", 610.9), ("51A", 640.0), ("52", 678.0))}
_LEFT = {n: (207.4, 309.2, y) for n, y in (
    ("19", 523.4), ("20", 542.8), ("21", 562.3), ("22", 581.7), ("23", 600.8), ("24", 620.2), ("25A", 639.6),
    ("25B", 659.5), ("26", 679.0), ("27", 698.9), ("28", 718.4))}
_SMW = {"9": (209.9, 308.6, 283.2), "10": (209.9, 308.6, 301.6)}
# Text boxes: key → (x, baseline, width)
_TEXT = {"4": (45.0, 159.0, 205.0), "6": (45.0, 187.4, 205.0), "13": (45.0, 371.6, 260.0),
         "14": (45.0, 398.0, 205.0), "17": (45.0, 467.6, 260.0)}
# One character per printed cell: key → (x0, x1, cells, baseline)
_COMBS = {"6A": (261.4, 309.4, 4, 187.4), "14A": (259.3, 307.3, 4, 398.0), "8": (167.2, 309.4, 11, 265.0)}
_TIN_ROWS = {"3": 133.5, "12": 346.0, "16": 442.2}
_TIN_CELLS = ((86.2, 124.1, 3), (135.9, 173.8, 3), (185.6, 223.5, 3), (235.2, 306.1, 5))


def template_sha256() -> str:
    return hashlib.sha256(TEMPLATE.read_bytes()).hexdigest()


def _w(text: str, size: float = SIZE) -> float:
    return fitz.get_text_length(text, fontname=FONT, fontsize=size)


def _fit(text: str, width: float, size: float = SIZE) -> tuple[str, float]:
    while size > 5.5 and _w(text, size) > width:
        size -= 0.5
    return text, size


def _amount(page, box, value) -> None:
    if not isinstance(value, Decimal) or value == 0:
        return
    x0, x1, y = box
    text = f"{value:,.2f}"
    page.insert_text((x1 - 3 - _w(text), y), text, fontname=FONT, fontsize=SIZE)


def _text(page, key: str, value: str) -> None:
    if not value:
        return
    x, y, width = _TEXT[key]
    text, size = _fit(value, width)
    page.insert_text((x, y), text, fontname=FONT, fontsize=size)


def _comb(page, x0: float, x1: float, n: int, y: float, chars: str) -> None:
    step = (x1 - x0) / n
    for i, ch in enumerate(chars[:n]):
        cx = x0 + step * (i + 0.5)
        page.insert_text((cx - _w(ch) / 2, y), ch, fontname=FONT, fontsize=SIZE)


def _tin(page, key: str, digits: str) -> None:
    digits = "".join(ch for ch in digits if ch.isdigit())
    if not digits:
        return
    digits = digits.ljust(14, "0")[:14]
    parts = (digits[:3], digits[3:6], digits[6:9], digits[9:14])
    for (x0, x1, n), part in zip(_TIN_CELLS, parts):
        _comb(page, x0, x1, n, _TIN_ROWS[key], part)


def _x(page, rect: tuple[float, float, float, float]) -> None:
    x0, y0, x1, y1 = rect
    page.insert_text(((x0 + x1) / 2 - _w("X", 9) / 2, y1 - 3), "X", fontname=FONT, fontsize=9)


def fill_2316(doc: fitz.Document, c: Computed, employer: dict) -> None:
    """Append one filled 2316 to ``doc``. ``employer``: tin (digits), name, address, zip."""
    with fitz.open(TEMPLATE) as blank:
        doc.insert_pdf(blank)
    page = doc[-1]
    f = c.form
    _comb(page, 124.8, 195.7, 4, 105.0, f["1"])
    _comb(page, 386.8, 456.7, 4, 105.0, f["2_from"].replace("/", ""))
    _comb(page, 512.4, 582.3, 4, 105.0, f["2_to"].replace("/", ""))
    _tin(page, "3", f["3"])
    _text(page, "4", f["4"].upper())
    _text(page, "6", f["6"])
    _comb(page, *_COMBS["6A"][:3], _COMBS["6A"][3], "".join(ch for ch in f["6A"] if ch.isalnum()))
    if f["7"]:
        mm, dd, yyyy = f["7"].split("/")
        _comb(page, 46.9, 97.2, 4, 265.0, mm + dd)
        _comb(page, 97.2, 147.6, 4, 265.0, yyyy)
    _comb(page, *_COMBS["8"][:3], _COMBS["8"][3], "".join(ch for ch in f["8"] if ch.isdigit()))
    for key, box in _SMW.items():
        _amount(page, box, f[key] if isinstance(f[key], Decimal) else None)
    if f["11"]:
        _x(page, (47.7, 309.9, 61.5, 322.4))
    _tin(page, "12", employer.get("tin", ""))
    _text(page, "13", employer.get("name", "").upper())
    _text(page, "14", employer.get("address", ""))
    _comb(page, *_COMBS["14A"][:3], _COMBS["14A"][3], "".join(ch for ch in employer.get("zip", "") if ch.isalnum()))
    _x(page, (115.9, 406.2, 129.6, 418.7))  # 15: main employer
    if f["16"]:
        _tin(page, "16", f["16"])
        _text(page, "17", f["17"].upper())
    for key, box in {**_LEFT, **_RIGHT}.items():
        _amount(page, box, f.get(key))


def build_2316_zip(computed: list[Computed], employer: dict, year: int) -> bytes:
    """One PDF per employee, zipped (``Last, First - 2316 - YEAR.pdf``), plus all of them in one PDF."""
    buf = io.BytesIO()
    combined = fitz.open()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        used: set[str] = set()
        for c in computed:
            doc = fitz.open()
            fill_2316(doc, c, employer)
            combined.insert_pdf(doc)
            name = f"{c.employee.last_name}, {c.employee.first_name}".strip(", ") or c.employee.id
            name = "".join(ch for ch in name if ch.isalnum() or ch in " ,.-")[:80]
            fname, i = f"{name} - 2316 - {year}.pdf", 2
            while fname in used:
                fname, i = f"{name} ({i}) - 2316 - {year}.pdf", i + 1
            used.add(fname)
            z.writestr(fname, doc.tobytes(garbage=3, deflate=True))
        if computed:
            z.writestr(f"All employees - 2316 - {year}.pdf", combined.tobytes(garbage=3, deflate=True))
    return buf.getvalue()


def issued_on(year: int) -> date:
    """2316s go to employees by January 31 of the following year."""
    return date(year + 1, 1, 31)
