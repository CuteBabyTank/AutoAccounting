"""Review fixes for the QBO 08 importers: row limits, CSV encodings, fuzzy matches, duplicates of documents."""

from datetime import date
from decimal import Decimal

import pytest

from app.services.accounting.payroll_import import MAX_ROWS, parse_sheet

D = Decimal


def test_parse_sheet_refuses_more_rows_than_the_limit_instead_of_cutting():
    body = "\n".join(f"{1000 + i},Account {i},1.00," for i in range(MAX_ROWS + 1))
    data = ("Account code,Account name,Debit,Credit\n" + body).encode()
    with pytest.raises(ValueError, match="more than"):
        parse_sheet(data, "tb.csv")
    ok = ("Account code,Account name,Debit,Credit\n" + "\n".join(body.split("\n")[:MAX_ROWS])).encode()
    assert len(parse_sheet(ok, "tb.csv")[1]) == MAX_ROWS


def test_parse_sheet_reads_a_windows_1252_csv():
    data = "Type,Customer,Invoice no.,Amount\nAR,Peñafrancia Trading,001,100\n".encode("cp1252")
    headers, rows = parse_sheet(data, "items.csv")
    assert rows[0][1] == "Peñafrancia Trading"
    bom = "﻿Type,Customer,Invoice no.,Amount\nAR,Ñino Corp,002,5\n".encode("utf-8")
    headers, rows = parse_sheet(bom, "items.csv")
    assert headers[0] == "Type" and rows[0][1] == "Ñino Corp"
