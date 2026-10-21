"""A workbook as data the browser can show (pure): sheets of cells with their displayed text and highlight.

Read-only and capped (rows and columns per sheet, cells overall) so a large ledger tab can't make a huge response.
"""

import io
from datetime import date, datetime
from decimal import Decimal

from openpyxl import load_workbook

MAX_ROWS = 1000
MAX_COLS = 40
MAX_CELLS = 150_000


def _text(value, number_format: str) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float, Decimal)):
        if "0.00" in number_format:
            return f"{value:,.2f}"
        if "#,##0" in number_format:
            return f"{value:,.0f}"
        return str(value)
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M") if (value.hour or value.minute) else value.strftime("%Y-%m-%d")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _fill(cell) -> str | None:
    fill = cell.fill
    if fill is None or fill.fill_type != "solid":
        return None
    rgb = fill.fgColor.rgb if fill.fgColor is not None and fill.fgColor.type == "rgb" else None
    if not isinstance(rgb, str) or len(rgb) not in (6, 8):
        return None
    rgb = rgb[-6:].upper()
    return None if rgb in ("FFFFFF", "000000") else f"#{rgb}"


def workbook_preview(data: bytes) -> list[dict]:
    """``[{name, rows: [[{v, fill?, bold?, num?, strike?}]], truncated}]`` in sheet order."""
    wb = load_workbook(io.BytesIO(data), data_only=True)
    sheets: list[dict] = []
    budget = MAX_CELLS
    try:
        for ws in wb.worksheets:
            max_row, max_col = ws.max_row or 0, min(ws.max_column or 0, MAX_COLS)
            take = min(max_row, MAX_ROWS, budget // max(max_col, 1))
            rows: list[list[dict]] = []
            for row in ws.iter_rows(min_row=1, max_row=take, max_col=max_col):
                out = []
                for cell in row:
                    entry: dict = {"v": _text(cell.value, cell.number_format or "")}
                    if isinstance(cell.value, (int, float, Decimal)) and not isinstance(cell.value, bool):
                        entry["num"] = True
                    fill = _fill(cell)
                    if fill:
                        entry["fill"] = fill
                    if cell.font is not None and cell.font.bold:
                        entry["bold"] = True
                    if cell.font is not None and cell.font.strike:
                        entry["strike"] = True
                    out.append(entry)
                rows.append(out)
            while rows and all(c["v"] == "" and "fill" not in c for c in rows[-1]):
                rows.pop()
            budget -= len(rows) * max(max_col, 1)
            sheets.append({"name": ws.title, "rows": rows,
                           "truncated": max_row > take or (ws.max_column or 0) > MAX_COLS})
    finally:
        wb.close()
    return sheets
