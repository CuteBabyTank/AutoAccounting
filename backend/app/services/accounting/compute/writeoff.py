"""Bulk write-off of customer invoices (pure).

A write-off is one journal entry: Dr the chosen expense (bad debts) for the total, Cr A/R per invoice at its open
balance (net of the customer's CWT and of payments, as the aging shows). The entry's ``writeoff_items`` link it to the
open items, which the subledger reads back as payments so the invoices close; deleting the entry reopens them.
"""

from datetime import date
from decimal import Decimal

from app.services.accounting.compute.books import Payment
from app.services.accounting.compute.money import ZERO, c2
from app.services.accounting.compute.subledger import OpenItem

MAX_ITEMS = 199   # one debit line + the credits fit the journal entry's 200-line limit


def candidates(items: list[OpenItem], min_days_past_due: int, max_balance: Decimal | None) -> list[OpenItem]:
    """Open customer invoices at least ``min_days_past_due`` past due (0 = any, due or not) with a balance up to
    ``max_balance``."""
    return [i for i in items
            if i.doc.kind == "ar" and i.open > 0 and (min_days_past_due <= 0 or i.days_past_due >= min_days_past_due)
            and (max_balance is None or i.open <= max_balance)]


def entry_lines(items: list[OpenItem], expense_code: str, ar_code: str) -> list[dict]:
    total = c2(sum((i.open for i in items), ZERO))
    lines = [{"account_code": expense_code, "debit": str(total), "credit": "0", "party_name": "", "party_tin": ""}]
    lines += [{"account_code": ar_code, "debit": "0", "credit": str(c2(i.open)), "party_name": i.doc.contact_name,
               "party_tin": i.doc.contact_tin} for i in items]
    return lines


def payments(rows: list[tuple[str, date, list[dict]]]) -> list[Payment]:
    """(entry id, entry date, writeoff_items) of live write-off entries → payments that settle the items."""
    return [Payment(f"wo:{je}:{x['id']}", str(x["id"]), on, c2(Decimal(str(x["amount"]))), "writeoff", "Write-off")
            for je, on, items in rows for x in items or []]
