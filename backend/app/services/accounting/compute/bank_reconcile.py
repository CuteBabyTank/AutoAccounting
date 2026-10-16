"""Bank reconciliation for one account and month, and the opening-balance check (pure).

Book balance = every posting to the account through the month end. A posting is *cleared* when a statement line
explains it (the line's own posting, the payment it is, the filed return or journal entry it was matched to);
postings dated before the first statement are in that statement's opening balance (brought forward). The rest are
uncleared (outstanding cheques, deposits in transit): statement balance + uncleared = book balance.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.services.accounting.compute.bank_books import MatchedLine
from app.services.accounting.compute.books import Entry
from app.services.accounting.compute.money import ZERO, c2

_CENT = Decimal("0.01")


@dataclass(frozen=True)
class Reconciliation:
    account: str
    month_start: date
    month_end: date
    statement_balance: Decimal
    book_balance: Decimal
    uncleared: tuple[dict, ...]          # {id, date, amount, label}
    open_lines: tuple[str, ...]          # statement lines still unmatched / suggested / ambiguous

    @property
    def outstanding(self) -> Decimal:
        return c2(sum((Decimal(u["amount"]) for u in self.uncleared), ZERO))

    @property
    def difference(self) -> Decimal:
        return c2(self.book_balance - self.statement_balance - self.outstanding)

    @property
    def ok(self) -> bool:
        return not self.open_lines and self.difference == 0


def cleared_entry_ids(lines: list[MatchedLine]) -> set[str]:
    """Ids of the book entries the matched lines stand for."""
    out: set[str] = set()
    for l in lines:
        if l.kind == "document":
            out |= {f"pay:bank:{l.id}", f"pay:rcpt:{l.ref}"}
        elif l.kind == "posting":
            out.add(f"bank:{l.id}")
        elif l.kind == "tax":
            form, period = l.ref.split(":", 1) if ":" in l.ref else (l.ref, "")
            out.add(f"tax:{form}:{period}:paid")
        elif l.kind == "journal":
            out.add(f"je:{l.ref}")
    return out


def account_postings(entries: list[Entry], account: str, through: date,
                     first_statement_start: date | None = None) -> list[dict]:
    out = []
    for e in entries:
        if first_statement_start is not None and _brought_forward(e, first_statement_start):
            continue
        if e.date > through:
            continue
        amount = c2(sum((l.debit - l.credit for l in e.lines if l.account == account), ZERO))
        if amount:
            label = " · ".join(p for p in (e.reference, e.party_name, e.particulars) if p)
            out.append({"id": e.id, "date": e.date.isoformat(), "amount": str(amount), "label": label})
    return out


def _brought_forward(e: Entry, first_statement_start: date) -> bool:
    """Dated before the first statement, or the opening balances (which stand before the books' first day)."""
    return e.date < first_statement_start or (e.source == "opening" and e.date <= first_statement_start)


def balance_before(entries: list[Entry], account: str, on: date) -> Decimal:
    return c2(sum((l.debit - l.credit for e in entries if _brought_forward(e, on) for l in e.lines
                   if l.account == account), ZERO))


def reconcile(account: str, month_start: date, month_end: date, statement_closing: Decimal, entries: list[Entry],
              cleared: set[str], first_statement_start: date, open_lines: list[str]) -> Reconciliation:
    since = account_postings(entries, account, month_end, first_statement_start)
    book = c2(balance_before(entries, account, first_statement_start) + sum((Decimal(p["amount"]) for p in since), ZERO))
    uncleared = tuple(p for p in since if p["id"] not in cleared)
    return Reconciliation(account, month_start, month_end, c2(statement_closing), book, uncleared, tuple(open_lines))


def opening_gap(entries: list[Entry], account: str, first_statement_start: date, opening: Decimal | None) -> dict | None:
    """The ``opening_balance_missing`` details when the first statement opens at a balance the books don't have."""
    if opening is None:
        return None
    books = balance_before(entries, account, first_statement_start)
    if abs(books - c2(opening)) < _CENT:
        return None
    return {"date": first_statement_start.isoformat(), "statement": str(c2(opening)), "books": str(books)}
