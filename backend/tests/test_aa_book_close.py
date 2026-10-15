"""Closed months: frozen entries, correcting entries, final numbers and loose-leaf pages (pure)."""

from datetime import date
from decimal import Decimal

import fitz

from app.services.accounting.books_pdf import Header, cover_page, month_pdf, sworn_declaration
from app.services.accounting.compute.book_close import (
    ClosedMonth, apply_closes, entry_from_json, entry_to_json, final_numbers,
)
from app.services.accounting.compute.book_ledgers import entry_numbers
from app.services.accounting.compute.books import Entry, Line

D = Decimal


def e(id, on, amount="100", book="GJ"):
    return Entry(id, on, book, "R1", "", "", "Test", "manual",
                 (Line("1020", debit=D(amount)), Line("4010", credit=D(amount))))


JAN = (date(2026, 1, 1), date(2026, 1, 31))


def closed(*entries):
    return ClosedMonth(*JAN, tuple(entries), ())


def test_entries_round_trip_through_json():
    x = e("a", date(2026, 1, 5))
    assert entry_from_json(entry_to_json(x)) == x


def test_unchanged_closed_entry_is_kept_and_open_months_pass_through():
    a, b = e("a", date(2026, 1, 5)), e("b", date(2026, 2, 3))
    out, warnings = apply_closes([a, b], [closed(a)])
    assert sorted(x.id for x in out) == ["a", "b"] and warnings == []


def test_changed_entry_is_reversed_and_reposted_in_the_first_open_month():
    old = e("a", date(2026, 1, 5), "100")
    new = e("a", date(2026, 1, 5), "120")
    out, warnings = apply_closes([new], [closed(old)])
    ids = {x.id: x for x in out}
    assert ids["a"].lines[0].debit == D("100")                  # the printed entry stays
    rev, rep = ids["fix:a:rev"], ids["fix:a:new"]
    assert rev.date == rep.date == date(2026, 2, 1) and rev.book == "GJ"
    assert rev.lines[0].credit == D("100") and rep.lines[0].debit == D("120")
    assert "Jan 2026 (2)" in warnings[0]


def test_removed_entry_is_reversed_and_late_entry_is_recorded_late():
    old = e("a", date(2026, 1, 5))
    late = e("late", date(2026, 1, 20))
    out, warnings = apply_closes([late], [closed(old)])
    ids = {x.id for x in out}
    assert {"a", "fix:a:rev", "fix:late:new"} <= ids and "late" not in ids
    assert next(x for x in out if x.id == "fix:late:new").particulars.startswith("Late recording")


def test_final_numbers_continue_and_open_months_number_after_them():
    a, b, c = e("a", date(2026, 1, 5)), e("b", date(2026, 1, 9)), e("c", date(2026, 2, 3))
    used = {"GJ": 4}
    numbers = final_numbers([a, b], 2026, used)
    assert numbers == {"a": "GJ-2026-0005", "b": "GJ-2026-0006"}
    assert entry_numbers([a, b, c], 12, numbers)["c"] == "GJ-2026-P0007"


def test_month_pdf_numbers_pages_and_carries_totals_forward():
    rows = [{"key": str(i), "date": "2026-01-05", "entry_no": f"GJ-2026-{i:04d}", "code": "1020",
             "account": "Cash in bank", "particulars": "Test", "debit": D("10"), "credit": D("0")} for i in range(120)]
    header = Header("Bayanihan Hardware Inc.", "123-456-789-00000", "Quezon City")
    data, count = month_pdf("GJ", rows, header, "For the month of January 2026", 7)
    doc = fitz.open(stream=data, filetype="pdf")
    assert count == doc.page_count >= 3
    assert doc[0].rect.width == 936 and doc[0].rect.height == 612   # 13" × 8.5" landscape
    assert "Page 7" in doc[0].get_text() and f"Page {6 + count}" in doc[-1].get_text()
    assert "Carried forward" in doc[0].get_text() and "Brought forward" in doc[1].get_text()
    assert "1,200.00" in doc[-1].get_text() and "Totals for the month" in doc[-1].get_text()


def test_empty_month_still_prints_a_page_and_binding_pages_render():
    header = Header("X Corp", "123-456-789-00000", "Manila", "040")
    data, count = month_pdf("CRJ", [], header, "For the month of March 2026", 1)
    assert count == 1 and "No transactions" in fitz.open(stream=data, filetype="pdf")[0].get_text()
    doc = fitz.open()
    cover_page(doc, header, "GL", 2026, date(2026, 1, 1), date(2026, 12, 31))
    sworn_declaration(doc, header, [("GL", 24)], 2026, date(2026, 1, 1), date(2026, 12, 31), "Juan Cruz", "President")
    text = doc[0].get_text() + doc[1].get_text()
    assert "GENERAL LEDGER" in text and "SWORN DECLARATION" in text and "Juan Cruz" in text and "24" in text
