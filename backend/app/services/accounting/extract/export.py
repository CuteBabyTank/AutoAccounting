"""The Excel file of one extract run and one format (pure).

Sheet "Records" has one row per document read; sheet "Lines" (only when the format has row fields) one row per
line. Money / number cells are numbers when the value parses as one, a flagged cell is filled yellow or red and
carries the flag message as a comment, and every text cell goes through `csv_safe`.
"""

import io
from decimal import Decimal, InvalidOperation
from typing import Any

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from app.services.spreadsheet_safe import csv_safe

_NUMERIC = ("money", "number", "percent")
_FILLS = {"yellow": PatternFill("solid", fgColor="FFF2CC"), "red": PatternFill("solid", fgColor="F8CBAD")}
_MONEY_FORMAT = "#,##0.00"
_BOLD = Font(bold=True)
_MAX_NUMBER_CHARS = 30
MAX_CELLS = 2_000_000
_TEXT_MAX = 32000  # Excel's cell limit is 32,767 characters


def cell_count(header_fields: int, row_fields: int, records: int, lines: int) -> int:
    """Cells the workbook would hold: each record has its header fields plus #, File, Pages and Needs review; each
    line its row fields plus Record # and Line."""
    return records * (header_fields + 4) + lines * (row_fields + 2)


def _text(value: Any) -> Any:
    """A text cell: characters Excel files can't hold removed, capped, then neutralised against formulas."""
    return csv_safe(ILLEGAL_CHARACTERS_RE.sub("", "" if value is None else str(value))[:_TEXT_MAX])


def _number(text: str) -> Decimal | None:
    clean = text.replace(",", "").strip()
    if not clean or len(clean) > _MAX_NUMBER_CHARS:
        return None
    try:
        value = Decimal(clean)
    except InvalidOperation:
        return None
    return value if value.is_finite() else None


def _put(ws, row: int, col: int, ftype: str, value: Any) -> None:
    text = "" if value is None else str(value)
    cell = ws.cell(row, col)
    number = _number(text) if ftype in _NUMERIC else None
    if number is not None:
        cell.value = float(number) if number != number.to_integral_value() else int(number)
        cell.number_format = _MONEY_FORMAT
    else:
        cell.value = _text(text)


def _mark(ws, row: int, col: int, level: str, message: str) -> None:
    cell = ws.cell(row, col)
    if level == "red" or cell.fill.fill_type is None:  # red wins over yellow
        cell.fill = _FILLS[level]
    text = _text(message)
    cell.comment = Comment(text if cell.comment is None else f"{cell.comment.text}\n{text}", "Extract")


def _head(ws, labels: list[str]) -> None:
    for col, label in enumerate(labels, 1):
        cell = ws.cell(1, col, _text(label))
        cell.font = _BOLD
    ws.freeze_panes = "A2"


def _widths(ws, widths: list[int]) -> None:
    for col, width in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(col)].width = width
        for row in ws.iter_rows(min_col=col, max_col=col, min_row=2):
            row[0].alignment = Alignment(vertical="top")


def _pages(record: dict) -> str:
    start, end = record.get("page_start"), record.get("page_end")
    if start is None:
        return ""
    return str(start) if end in (None, start) else f"{start}-{end}"


def workbook(format_name: str, snapshot: dict, records: list[dict]) -> bytes:
    """The .xlsx bytes. `records` are in export order: `position`, `file`, `page_start`, `page_end`, `values`
    (`{"header": {...}, "rows": [...]}`) and `flags`. The "#" column counts from 1 in that order."""
    fields = snapshot.get("fields", [])
    header = [f for f in fields if f.get("scope") == "header"]
    rows = [f for f in fields if f.get("scope") == "row"]
    wb = Workbook()
    ws = wb.active
    ws.title = "Records"
    _head(ws, ["#", "File", "Pages", *[f["label"] for f in header], "Needs review"])
    review_col = 3 + len(header) + 1
    head_col = {f["key"]: 4 + i for i, f in enumerate(header)}
    lines = None
    row_col = {f["key"]: 3 + i for i, f in enumerate(rows)}
    if rows:
        lines = wb.create_sheet("Lines")
        _head(lines, ["Record #", "Line", *[f["label"] for f in rows]])
    line_at = 2
    for n, rec in enumerate(records, 1):
        r = n + 1
        values = rec.get("values") or {}
        ws.cell(r, 1, n)
        ws.cell(r, 2, _text(rec.get("file") or ""))
        ws.cell(r, 3, _pages(rec))
        head_values = values.get("header") or {}
        for f in header:
            _put(ws, r, head_col[f["key"]], f["type"], head_values.get(f["key"]))
        first_line = line_at
        if lines is not None:
            for i, item in enumerate(values.get("rows") or [], 1):
                lines.cell(line_at, 1, n)
                lines.cell(line_at, 2, i)
                for f in rows:
                    _put(lines, line_at, row_col[f["key"]], f["type"], item.get(f["key"]) if isinstance(item, dict) else None)
                line_at += 1
        messages: list[str] = []
        for flag in rec.get("flags") or []:
            level = flag.get("level") if flag.get("level") in _FILLS else "yellow"
            message = str(flag.get("message") or "")
            if message and message not in messages:
                messages.append(message)
            for cell in flag.get("cells") or []:
                key, at = cell.get("key"), cell.get("row")
                if at is None and key in head_col:
                    _mark(ws, r, head_col[key], level, message)
                elif lines is not None and key in row_col and isinstance(at, int) and first_line + at < line_at:
                    _mark(lines, first_line + at, row_col[key], level, message)
        ws.cell(r, review_col, _text("; ".join(messages)))
    _widths(ws, [6, 28, 8, *[18] * len(header), 40])
    if lines is not None:
        _widths(lines, [10, 6, *[18] * len(rows)])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
