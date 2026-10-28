"""Fill a flat BIR form from a ``FormLayout`` (PyMuPDF overlay, one character per comb cell)."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

import fitz  # PyMuPDF

from app.forms.overlay import Amount, Cells, FormLayout

FONT = "helv"
CELL_SIZE = 9.0
CHECK_SIZE = 9.0
YELLOW_RGB = (1.0, 0.957, 0.702)
RED_RGB = (0.71, 0.14, 0.09)
BLACK = (0, 0, 0)


@dataclass(frozen=True)
class Rendered:
    pdf: bytes
    overflow: tuple[str, ...]  # amount keys whose digits did not fit their cells


def amount_chars(text: str, whole: bool) -> tuple[list[str], list[str]] | None:
    """'-1234.5' -> (['(', '1', '2', '3', '4'], ['5', '0)']); whole pesos -> (['(', '1', '2', '3', '5', ')'], [])."""
    try:
        value = Decimal(text)
    except (InvalidOperation, TypeError, ValueError):
        return None
    negative = value < 0
    if whole:
        digits = list(str(abs(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP)))
        return (["("] + digits + [")"] if negative else digits), []
    pesos, cents = f"{abs(value):.2f}".split(".")
    cents_chars = list(cents)
    if negative:
        cents_chars[-1] += ")"
        return ["("] + list(pesos), cents_chars
    return list(pesos), cents_chars


def _width(text: str, size: float) -> float:
    return fitz.get_text_length(text, fontname=FONT, fontsize=size)


def _centre(page, x: float, y: float, text: str, size: float = CELL_SIZE) -> None:
    page.insert_text((x - _width(text, size) / 2, y), text, fontname=FONT, fontsize=size, color=BLACK)


def _in_cells(page, cells, baseline: float, chars: list[str]) -> None:
    for (x0, x1), char in zip(cells, chars):
        if char.strip():
            _centre(page, (x0 + x1) / 2, baseline, char)


def _write_cells(page, spec: Cells, text: str) -> None:
    if len(spec.cells) == 1:
        x0, x1 = spec.cells[0]
        _centre(page, (x0 + x1) / 2, spec.baseline, text)
        return
    chars = list(text[: len(spec.cells)])
    cells = spec.cells[len(spec.cells) - len(chars):] if spec.align == "right" else spec.cells
    _in_cells(page, cells, spec.baseline, chars)


def _write_amount(page, spec: Amount, text: str) -> bool:
    """Write an amount; False when its digits overflow the pesos cells (then printed right-aligned, uncut)."""
    parts = amount_chars(text, whole=not spec.cents)
    if parts is None:
        return True
    pesos, cents = parts
    _in_cells(page, spec.cents, spec.baseline, cents)
    if len(pesos) <= len(spec.pesos):
        _in_cells(page, spec.pesos[len(spec.pesos) - len(pesos):], spec.baseline, pesos)
        return True
    right = spec.pesos[-1][1] - 1
    joined = "".join(pesos)
    page.insert_text((right - _width(joined, CELL_SIZE), spec.baseline), joined, fontname=FONT,
                     fontsize=CELL_SIZE, color=RED_RGB)
    return False


def _highlight(page, spec: Amount) -> None:
    x0 = spec.pesos[0][0]
    x1 = (spec.cents or spec.pesos)[-1][1]
    page.draw_rect(fitz.Rect(x0, spec.baseline - 9, x1, spec.baseline + 2.5), color=None, fill=YELLOW_RGB,
                   fill_opacity=0.85, overlay=True)


def banner_text(draft_reviews: int, missing: Sequence[str]) -> str | None:
    parts = []
    if missing:
        parts.append("Missing: " + ", ".join(missing))
    if draft_reviews:
        parts.append(f"{draft_reviews} document(s) unreviewed")
    return f"DRAFT, not for filing. {' · '.join(parts)}." if parts else None


def draw_banner(doc, point: tuple[float, float], text: str, size: float) -> None:
    """The red draft line on every page, shrunk to fit the page width."""
    for page in doc:
        room = page.rect.width - point[0] - 12
        width = sum(_width(char, size) for char in text)  # whole-string length undercounts non-ASCII (· ₱)
        fitted = min(size, size * room / max(width, 1))
        page.insert_text(point, text, fontname=FONT, fontsize=fitted, color=RED_RGB)


def render_form(layout: FormLayout, *, amounts: dict[str, str], cells: dict[str, str] | None = None,
                checks: Iterable[str] = (), highlights: frozenset[str] = frozenset(),
                draft_reviews: int = 0, notes: Sequence[str] = (), missing: Sequence[str] = ()) -> Rendered:
    doc = fitz.open(layout.template)
    overflow: list[str] = []
    try:
        for key, text in (cells or {}).items():
            spec = layout.cells.get(key)
            if spec is not None and text:
                _write_cells(doc[spec.page], spec, text)
        for key in checks:
            spec = layout.checks.get(key)
            if spec is not None:
                _centre(doc[spec.page], spec.x, spec.baseline, "X", CHECK_SIZE)
        for key, text in amounts.items():
            spec = layout.amounts.get(key)
            if spec is None or text in (None, ""):
                continue
            page = doc[spec.page]
            if key in highlights:
                _highlight(page, spec)
            if not _write_amount(page, spec, text):
                overflow.append(key)

        notes = list(notes)
        if any(key in layout.amounts for key in highlights):
            notes.append("Highlighted = changed since the previous version")
        if overflow:
            notes.append("Too long for the boxes (printed in red): " + ", ".join(overflow))
        if notes:
            first = doc[0]
            first.insert_text((24, first.rect.height - 3), " · ".join(notes), fontname=FONT, fontsize=7,
                              color=BLACK)
        banner = banner_text(draft_reviews, missing)
        if banner:
            draw_banner(doc, (24, 10), banner, 9)
        return Rendered(doc.tobytes(garbage=3, deflate=True), tuple(overflow))
    finally:
        doc.close()
