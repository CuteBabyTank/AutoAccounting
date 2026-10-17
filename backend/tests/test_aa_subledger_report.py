"""Aging XLSX / PDF, the customer statement, and the aging tabs a quarter version stores."""

import io
from datetime import date
from decimal import Decimal

import fitz
from openpyxl import load_workbook

from app.services.accounting.books_pdf import Header
from app.services.accounting.compute.specs import LEDGER_COLUMNS, LEDGER_ORDER
from app.services.accounting.compute.subledger import aging, aging_totals, open_items
from app.services.accounting.subledger_report import (
    aging_ledger_rows, aging_pdf, aging_xlsx, items_from_ledger, statement_pdf,
)
from tests.test_aa_subledger import AS_OF, doc, q4_bills, q4_sales

HEADER = Header("Bayanihan Hardware Trading Corp.", "123-456-789-00000", "Marikina City")


def _text(pdf: bytes) -> str:
    return "\n".join(page.get_text() for page in fitz.open(stream=pdf, filetype="pdf"))


def _ap():
    docs, payments = q4_bills()
    items = open_items(docs, payments, AS_OF, {})
    return items, aging(items)


def test_aging_pdf_has_totals_and_unverified_note():
    items, rows = _ap()
    text = _text(aging_pdf(HEADER, "ap", AS_OF, rows, aging_totals(rows), items))
    assert "ACCOUNTS PAYABLE AGING" in text and "757,042.80" in text and "160,227.20" in text
    assert "unverified" in text


def test_aging_xlsx_cells_are_formula_safe():
    d = doc("=HYPERLINK(1)", "ar", "=cmd|' /C calc'!A0", date(2026, 12, 1), "100.00")
    items = open_items([d], [], AS_OF, {})
    rows = aging(items)
    wb = load_workbook(io.BytesIO(aging_xlsx(HEADER, "ar", AS_OF, rows, aging_totals(rows), items)))
    assert not str(wb["Aging"]["A5"].value).startswith("=")
    assert not str(wb["Open items"]["C2"].value).startswith("=")
    assert wb["Aging"]["H6"].value == Decimal("100.00")


def test_statement_pdf_lists_open_invoices_and_2307_request():
    docs, payments = q4_sales()
    items = [i for i in open_items(docs, payments, AS_OF, {}) if i.doc.contact_name.startswith("Kalayaan")]
    text = _text(statement_pdf(HEADER, {"name": "Kalayaan Construction Co.", "tin": "400-500-600"}, AS_OF, items,
                               Decimal("2415.70")))
    assert "STATEMENT OF ACCOUNT" in text and "268,142.70" in text and "2,415.70" in text


def test_aging_tabs_round_trip_for_the_version_pdf():
    items, _ = _ap()
    rows = aging_ledger_rows(items)
    assert len(rows) == 8 and all(r["key"] for r in rows)
    assert {k for k, _, _ in LEDGER_COLUMNS["APAging"]} <= set(rows[0])
    back = items_from_ledger("ap", rows)
    assert aging_totals(aging(back)) == aging_totals(aging(items))
    assert "ARAging" in LEDGER_ORDER and "APAging" in LEDGER_ORDER


def _spans(pdf: bytes) -> list[tuple[str, fitz.Rect]]:
    page = fitz.open(stream=pdf, filetype="pdf")[0]
    return [(s["text"], fitz.Rect(s["bbox"])) for b in page.get_text("dict")["blocks"] for line in b.get("lines", [])
            for s in line["spans"]]


def test_long_names_are_cut_before_the_next_column():
    long = "Pacific Integrated Hardware, Construction Supply and General Merchandise Trading Corporation"
    from dataclasses import replace

    d = replace(doc("SI-2026-000000088548-LONG-REFERENCE", "ap", long, date(2026, 10, 1), "1000.00"),
                contact_tin="111222333")
    items = open_items([d], [], AS_OF, {})
    rows = aging(items)
    spans = _spans(aging_pdf(HEADER, "ap", AS_OF, rows, aging_totals(rows), items))
    names = [r for t, r in spans if t.startswith("Pacific")]
    tins = [r for t, r in spans if t == d.contact_tin]
    numbers = [r for t, r in spans if t.startswith("SI-2026")]
    assert len(names) == 2 and tins and numbers
    assert names[0].x1 <= tins[0].x0          # summary: name, then TIN
    assert names[1].x1 <= numbers[0].x0       # open items: name, then document number
    spans = _spans(statement_pdf(HEADER, {"name": long, "tin": ""}, AS_OF, items, Decimal("0")))
    number = next(r for t, r in spans if t.startswith("SI-2026"))
    on = next(r for t, r in spans if t == "2026-10-01")
    assert number.x1 <= on.x0
