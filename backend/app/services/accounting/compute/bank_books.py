"""Turn matched bank statement lines into the books' payments and postings, without counting anything twice (pure).

A line matched to a document is that document's payment: it replaces the ``paid_on`` payment. A line matched to a
receipt that pays an invoice moves that receipt's payment into the bank account on the line's date. A line matched
to a filed return or a journal entry adds nothing (they already post), apart from naming the bank account the tax
left from. The two sides of a transfer between own bank accounts post once. Lines with no bank account resolved
yet post nothing.
"""

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal

from app.services.accounting.compute.books import BankPosting, FiledPayment, Payment
from app.services.accounting.compute.money import c2

POSTING_STATUSES = frozenset({"matched", "confirmed"})
TRANSFER_DAYS = 7     # the two sides of a transfer between own accounts can clear a few days apart


@dataclass(frozen=True)
class MatchedLine:
    id: str
    on: date
    amount: Decimal              # signed
    account_code: str
    kind: str                    # document | posting | tax | journal
    ref: str                     # document id / filed-tax key "<form>:<year>Q<quarter>" / journal entry id
    match_amount: Decimal | None
    posting_account: str = ""
    narration: str = ""
    check_no: str = ""


def tax_key(form: str, year: int, quarter: int) -> str:
    return f"{form}:{year}Q{quarter}"


def apply_bank_lines(payments: list[Payment], filed: tuple[FiledPayment, ...] | list[FiledPayment],
                     lines: list[MatchedLine]) -> tuple[list[Payment], tuple[FiledPayment, ...], list[BankPosting]]:
    payments = list(payments)
    filed = list(filed)
    postings: list[BankPosting] = []
    moved: set[str] = set()          # receipt payments a line already moved into the bank
    paired: set[str] = set()         # transfer postings whose other side (on the other account's statement) is seen
    for l in sorted(lines, key=lambda x: (x.on, x.id)):
        if not l.account_code:
            continue
        amount = c2(l.match_amount if l.match_amount is not None else abs(l.amount))
        ref = (l.check_no or l.narration)[:60]
        if l.kind == "document":
            receipt = next((i for i, p in enumerate(payments) if p.id == f"rcpt:{l.ref}"), None)
            if receipt is None:  # the invoice itself was picked, but a linked receipt already pays it
                receipt = next((i for i, p in enumerate(payments) if p.id.startswith("rcpt:")
                                and p.settles == l.ref and p.id not in moved), None)
            if receipt is not None:
                moved.add(payments[receipt].id)
                payments[receipt] = replace(payments[receipt], on=l.on, via="bank", account=l.account_code)
                continue
            payments = [p for p in payments if p.id != f"paid:{l.ref}"]
            payments.append(Payment(f"bank:{l.id}", l.ref, l.on, amount, "bank", ref, l.account_code))
        elif l.kind == "tax":
            filed = [replace(f, account=l.account_code) if tax_key(f.form, f.year, f.quarter) == l.ref else f
                     for f in filed]
        elif l.kind == "posting" and l.posting_account:
            mirror = next((p for p in postings if p.id not in paired and p.bank_account == l.posting_account
                           and p.counter_account == l.account_code and p.amount == -c2(l.amount)
                           and abs((l.on - p.on).days) <= TRANSFER_DAYS), None)
            if mirror is not None:  # the other side of a transfer between own accounts: it already posted
                paired.add(mirror.id)
                continue
            postings.append(BankPosting(l.id, l.on, c2(l.amount), l.account_code, l.posting_account,
                                        l.narration[:255], l.check_no))
    return payments, tuple(filed), postings
