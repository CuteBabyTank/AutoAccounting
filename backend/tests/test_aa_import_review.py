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


# --- a closest-name match needs the person's confirmation ---------------------------------------------------------

from app.services.accounting.books.chart import Chart, standard_chart  # noqa: E402
from app.services.accounting.import_rows import build_journals, build_tb  # noqa: E402
from app.services.accounting.importing import AccountRef, source_key  # noqa: E402

REFS = [AccountRef(a.code, a.name, a.active, a.locked) for a in Chart(standard_chart("corporation")).accounts]
TB_HEAD = ["Account code", "Account name", "Debit", "Credit"]
TB_COLS = {"account_code": "Account code", "account_name": "Account name", "debit": "Debit", "credit": "Credit"}


def test_tb_closest_name_match_is_not_posted_until_confirmed():
    # "Professional fees payable" is closest to the expense "Professional fees": a liability would land in the P&L
    rows = [["1020", "", "500", ""], ["", "Professional fees payable", "", "500"]]
    r = build_tb(TB_HEAD, rows, TB_COLS, REFS, {})
    fuzzy = next(a for a in r.accounts if a.name_in == "Professional fees payable")
    assert (fuzzy.match.how, fuzzy.chosen, fuzzy.problem) == ("fuzzy", "6040", "unconfirmed")
    assert not r.ready and any("closest" in e.message for e in r.errors)
    r = build_tb(TB_HEAD, rows, TB_COLS, REFS, {source_key("", "Professional fees payable"): "6040"})
    assert r.ready                                  # the person confirmed it (or picked another account)


def test_je_closest_name_match_blocks_the_entry_until_confirmed():
    head = ["Date", "Account name", "Debit", "Credit"]
    cols = {"date": "Date", "account_name": "Account name", "debit": "Debit", "credit": "Credit"}
    rows = [["2026-01-31", "Rent income", "", "100"], ["2026-01-31", "Cash in bank", "100", ""]]
    r = build_journals(head, rows, cols, REFS, {}, books_start=date(2026, 1, 1))
    assert not r.ready and any("closest" in m for m in r.entries[0].errors)
    r = build_journals(head, rows, cols, REFS, {source_key("", "Rent income"): "4100"}, books_start=date(2026, 1, 1))
    assert r.ready and r.entries[0].lines[0]["account_code"] == "4100"
