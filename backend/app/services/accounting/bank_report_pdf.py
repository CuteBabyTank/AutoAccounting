"""Bank reconciliation report PDF, filed in the month's books folder (PyMuPDF)."""

from decimal import Decimal

import fitz

from app.services.accounting.books_pdf import BOLD, FONT, MARGIN, Header, _fit
from app.services.accounting.compute.bank_reconcile import Reconciliation

_PAGE = fitz.Rect(0, 0, 612, 936)     # 8.5" × 13" portrait
_ROW = 13


def _peso(value: Decimal) -> str:
    return f"{value:,.2f}" if value >= 0 else f"({-value:,.2f})"   # Helvetica has no peso sign


def reconciliation_pdf(header: Header, account_label: str, rec: Reconciliation, prepared_by: str = "") -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=_PAGE.width, height=_PAGE.height)
    y = MARGIN + 6

    def line(text: str, x: float = MARGIN, bold: bool = False, size: float = 9, right: str | None = None) -> None:
        nonlocal y, page
        if y > _PAGE.height - MARGIN - _ROW:
            page = doc.new_page(width=_PAGE.width, height=_PAGE.height)
            y = MARGIN + 6
        font = BOLD if bold else FONT
        page.insert_text((x, y), _fit(text, _PAGE.width - x - MARGIN - 110, font, size), fontname=font, fontsize=size)
        if right is not None:
            width = fitz.get_text_length(right, fontname=font, fontsize=size)
            page.insert_text((_PAGE.width - MARGIN - width, y), right, fontname=font, fontsize=size)
        y += _ROW

    line(header.name.upper(), bold=True, size=11)
    line(f"TIN {header.tin}   ·   {header.address}", size=8)
    y += 6
    line("BANK RECONCILIATION", bold=True, size=11)
    line(f"{account_label}   ·   as of {rec.month_end:%B %d, %Y}", size=9)
    y += 8
    line("Balance per bank statement", bold=True, right=_peso(rec.statement_balance))
    deposits = [u for u in rec.uncleared if Decimal(u["amount"]) > 0]
    checks = [u for u in rec.uncleared if Decimal(u["amount"]) < 0]
    line("Add: deposits in transit", right=_peso(sum((Decimal(u["amount"]) for u in deposits), Decimal("0"))))
    for u in deposits:
        line(f"{u['date']}   {u['label']}", x=MARGIN + 18, size=8, right=_peso(Decimal(u["amount"])))
    line("Less: outstanding checks and debits", right=_peso(-sum((Decimal(u["amount"]) for u in checks), Decimal("0"))))
    for u in checks:
        line(f"{u['date']}   {u['label']}", x=MARGIN + 18, size=8, right=_peso(-Decimal(u["amount"])))
    line("Adjusted bank balance", bold=True, right=_peso(rec.statement_balance + rec.outstanding))
    y += 4
    line("Balance per books", bold=True, right=_peso(rec.book_balance))
    line("Difference", bold=True, right=_peso(rec.difference))
    y += 10
    status = "Reconciled" if rec.ok else f"Not reconciled ({len(rec.open_lines)} statement line(s) still open)"
    line(status, bold=True)
    if prepared_by:
        line(f"Prepared by {prepared_by}", size=8)
    return doc.tobytes(garbage=3, deflate=True)
