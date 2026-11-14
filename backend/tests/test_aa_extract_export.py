import io

from openpyxl import load_workbook

from app.services.accounting.extract import builtins, export

SNAP = {"name": "Invoice", "fields": builtins.BUILTINS["invoice"]["fields"],
        "checks": builtins.BUILTINS["invoice"]["checks"]}


def record(n, total, flags=()):
    header = {f["key"]: "" for f in SNAP["fields"] if f["scope"] == "header"}
    header.update(seller_name="=HYPERLINK(\"http://x\")", total_amount=total)
    return {"position": n, "file": "a.pdf", "page_start": n, "page_end": n,
            "values": {"header": header, "rows": [{"description": "Cement", "quantity": "2", "unit_price": "100.00",
                                                   "amount": "200.00"}]}, "flags": list(flags)}


def test_workbook_sheets_safe_cells_numbers_and_fills():
    red = {"check_id": "c_x", "level": "red", "message": "Totals differ", "cells": [{"key": "total_amount", "row": None}]}
    wb = load_workbook(io.BytesIO(export.workbook("Invoice", SNAP, [record(1, "1120.00"), record(2, "99.00", [red])])))
    assert wb.sheetnames == ["Records", "Lines"]
    ws = wb["Records"]
    head = [c.value for c in ws[1]]
    col = head.index("Total amount") + 1
    assert ws.cell(2, col).value == 1120 and ws.cell(2, col).fill.fgColor.rgb in (None, "00000000")
    assert ws.cell(3, col).fill.fgColor.rgb.endswith("F8CBAD") and "Totals differ" in ws.cell(3, col).comment.text
    assert str(ws.cell(2, head.index("Seller name") + 1).value).startswith("'")
    assert ws.cell(3, head.index("Needs review") + 1).value == "Totals differ"
    assert wb["Lines"].max_row == 3


def test_no_lines_sheet_without_row_fields():
    snap = {"name": "Receipt", "fields": builtins.BUILTINS["receipt"]["fields"], "checks": []}
    r = record(1, "10.00")
    r["values"]["rows"] = []
    r["values"]["header"] = {f["key"]: "" for f in snap["fields"]}
    assert load_workbook(io.BytesIO(export.workbook("Receipt", snap, [r]))).sheetnames == ["Records"]


def test_flag_text_is_neutralised_and_non_numeric_money_stays_text():
    bad = {"check_id": "c_x", "level": "yellow", "message": "=cmd|' /C calc'!A0",
           "cells": [{"key": "total_amount", "row": None}]}
    wb = load_workbook(io.BytesIO(export.workbook("Invoice", SNAP, [record(1, "=1+1", [bad])])))
    ws = wb["Records"]
    head = [c.value for c in ws[1]]
    total = ws.cell(2, head.index("Total amount") + 1)
    assert total.value == "'=1+1" and total.fill.fgColor.rgb.endswith("FFF2CC")
    assert total.comment.text.startswith("'=")
    assert ws.cell(2, head.index("Needs review") + 1).value.startswith("'=")


def test_row_flag_marks_the_line_cell_and_numbers_run_in_export_order():
    flag = {"check_id": "c_y", "level": "yellow", "message": "Line off", "cells": [{"key": "amount", "row": 0}]}
    wb = load_workbook(io.BytesIO(export.workbook("Invoice", SNAP, [record(7, "1.00"), record(9, "2.00", [flag])])))
    assert [wb["Records"].cell(r, 1).value for r in (2, 3)] == [1, 2]
    lines = wb["Lines"]
    col = [c.value for c in lines[1]].index("Amount") + 1
    assert lines.cell(3, col).fill.fgColor.rgb.endswith("FFF2CC") and lines.cell(3, 1).value == 2
    assert lines.cell(2, col).comment is None


def test_control_characters_do_not_break_the_export():
    r = record(1, "10.00")
    r["values"]["header"].update(seller_name="A\x00B\x07C\x1f", buyer_name="\x00=HYPERLINK(\"http://x\")")
    flag = {"check_id": "c_x", "level": "red", "message": "\x00=bad\x07", "cells": [{"key": "seller_name", "row": None}]}
    r["flags"] = [flag]
    r["file"] = "a\x00.pdf"
    wb = load_workbook(io.BytesIO(export.workbook("Invoice", SNAP, [r])))
    ws = wb["Records"]
    head = [c.value for c in ws[1]]
    assert ws.cell(2, head.index("Seller name") + 1).value == "ABC"
    assert ws.cell(2, head.index("Buyer name") + 1).value.startswith("'=")
    assert ws.cell(2, head.index("Needs review") + 1).value == "'=bad"
    assert ws.cell(2, 2).value == "a.pdf"


def test_text_is_capped():
    r = record(1, "10.00")
    r["values"]["header"]["seller_name"] = "x" * 40000
    ws = load_workbook(io.BytesIO(export.workbook("Invoice", SNAP, [r])))["Records"]
    head = [c.value for c in ws[1]]
    assert len(ws.cell(2, head.index("Seller name") + 1).value) == 32000


def test_cell_count():
    assert export.cell_count(10, 5, 100, 300) == 100 * 14 + 300 * 7
    assert export.MAX_CELLS == 2_000_000
