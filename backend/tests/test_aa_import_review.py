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


# --- an opening item that is already an uploaded document would age twice ----------------------------------------

from app.services.accounting.import_rows import build_open_items, document_keys, item_key  # noqa: E402

OPEN_HEAD = ["Type", "Customer", "TIN", "Invoice no.", "Invoice date", "Amount"]
OPEN_COLS = {"kind": "Type", "contact_name": "Customer", "contact_tin": "TIN", "doc_number": "Invoice no.",
             "doc_date": "Invoice date", "amount": "Amount"}


def test_open_items_skip_invoices_already_uploaded_as_documents():
    rows = [["AR", "Mabuhay Builders Inc.", "", "0003", "2025-12-10", "150000"],
            ["AR", "Other Buyer", "123-456-789", "0004", "2025-12-11", "1000"],
            ["AP", "Pacific Steel", "", "PS-1", "2025-12-12", "800"]]
    uploaded = document_keys([("ar", "MABUHAY BUILDERS, INC.", "", "0003"),      # same name and number
                              ("ar", "Renamed Buyer", "123456789000", "0004"),     # same TIN and number
                              ("ap", "Pacific Steel", "", "PS-2")])                # another bill
    r = build_open_items(OPEN_HEAD, rows, OPEN_COLS, date(2026, 1, 1), documents=uploaded)
    assert [i.doc_number for i in r.items] == ["PS-1"] and r.ready
    assert r.documented == 2 and any("uploaded" in w for w in r.warnings)
    assert item_key("ar", "Mabuhay Builders Inc.", "0003") == item_key("ar", "MABUHAY BUILDERS INC", "0003")


# --- what the preview calls ready must also post ------------------------------------------------------------------

def test_tb_over_the_entry_line_limit_is_not_ready():
    chart = [AccountRef(str(1000 + i), f"Account {i}") for i in range(202)]
    rows = [[str(1000 + i), "", "1", ""] for i in range(201)] + [["1201", "", "", "201"]]
    r = build_tb(TB_HEAD, rows, TB_COLS, chart, {})
    assert len(r.lines) == 202 and not r.ready and any("200" in e.message for e in r.errors)


def test_amounts_too_large_for_the_books_are_row_errors():
    r = build_tb(TB_HEAD, [["1020", "", "1e13", ""], ["3010", "", "", "1e13"]], TB_COLS, REFS, {})
    assert not r.ready and r.errors[0].row == 1
    rows = [["AR", "Big Buyer", "", "1", "2025-12-10", "10000000000000"]]
    o = build_open_items(OPEN_HEAD, rows, OPEN_COLS, date(2026, 1, 1))
    assert not o.ready and o.errors[0].row == 1


def test_je_reimport_warns_about_entries_already_posted():
    head = ["Date", "Reference", "Account code", "Debit", "Credit"]
    cols = {"date": "Date", "reference": "Reference", "account_code": "Account code", "debit": "Debit",
            "credit": "Credit"}
    rows = [["2026-01-31", "PR-01", "6010", "100", ""], ["2026-01-31", "PR-01", "1020", "", "100"],
            ["2026-02-28", "PR-02", "6010", "90", ""], ["2026-02-28", "PR-02", "1020", "", "90"]]
    posted = {(date(2026, 1, 31), "PR-01", D("100.00"))}
    r = build_journals(head, rows, cols, REFS, {}, books_start=date(2026, 1, 1), posted=posted)
    assert r.ready and any("already" in w and "1 " in w for w in r.warnings)
    assert not build_journals(head, rows, cols, REFS, {}, books_start=date(2026, 1, 1)).warnings
