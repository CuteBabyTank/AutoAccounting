"""Undo a whole import batch (pure): what it deletes or restores and why it may be refused.

A confirmed import is an ``aa_import_batches`` row; the rows it wrote carry its ``import_batch_id`` and their
fingerprints are kept on the batch (``written``), so an undo can tell a row a person edited since. The opening TB
import replaces the company's single opening entry, so its batch also keeps the entry as it was before (``restore``).
The router gathers the facts (closes, filed quarters, reconciliations, bank lines, payments, write-offs) and asks
``undo_problem``; nothing here touches the database.
"""

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

from app.services.accounting.audit import json_safe
from app.services.accounting.periods import period_for

KIND_LABELS = {"opening-tb": "opening balances", "open-items": "open items", "journal-entries": "journal entries"}
ENTRY_STATE_FIELDS = ("id", "kind", "book", "entry_date", "reference", "particulars", "lines", "is_adjusting",
                      "import_batch_id")
_NOT_CONTENT = frozenset({"id", "import_batch_id"})
_SHOWN = 5


def entry_state(row) -> dict:
    """A journal entry's fields, JSON-safe: what a batch keeps to restore it and to fingerprint it."""
    return {name: json_safe(getattr(row, name, None)) for name in ENTRY_STATE_FIELDS}


def fingerprint(state: dict) -> str:
    """A digest of an entry's content (not its id or batch tag), stable under JSONB key order."""
    content = {k: v for k, v in json_safe(state).items() if k not in _NOT_CONTENT}
    return hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def entries_plan(written: dict[str, str], live: Iterable) -> tuple[list[str], list[str]]:
    """(ids to delete, ids edited since the import) among the batch's live journal entries."""
    delete, edited = [], []
    for row in live:
        key = str(row.id)
        delete.append(key)
        if key in written and written[key] != fingerprint(entry_state(row)):
            edited.append(key)
    return delete, edited


@dataclass(frozen=True)
class OpeningPlan:
    action: str                 # delete | restore
    restore: dict | None        # the prior opening entry's fields (restore)
    problem: str = ""


def opening_plan(batch_id: str, restore: dict, written: dict[str, str], current) -> OpeningPlan:
    """How to undo an opening TB import given the company's opening entry now (``None`` when there is none)."""
    prior = (restore or {}).get("opening")
    action = "restore" if prior else "delete"
    if current is None:
        return OpeningPlan(action, prior, "The opening balances were deleted after this import, so there is nothing "
                                          "to undo")
    tag = str(current.import_batch_id) if current.import_batch_id else ""
    if tag != str(batch_id):
        return OpeningPlan(action, prior, "A later import replaced these opening balances; undo that one first"
                           if tag else "The opening balances were replaced after this import")
    key = str(current.id)
    if key not in written:
        return OpeningPlan(action, prior, "The opening balances were replaced after this import")
    if written[key] != fingerprint(entry_state(current)):
        return OpeningPlan(action, prior, "The opening balances were edited after this import; change them on the "
                                          "Journal entries page instead")
    return OpeningPlan(action, prior)


def batch_status(kind: str, batch_id: str, undone: bool, opening_tag: str | None, live: int | None = None) -> str:
    """``undone``, ``replaced`` (an opening TB import a later import or edit took over), ``emptied`` (every row it
    wrote was deleted by hand since) or ``active``."""
    if undone:
        return "undone"
    if kind == "opening-tb":
        return "active" if (opening_tag or "") == str(batch_id) else "replaced"
    return "emptied" if live == 0 else "active"


def closed_hits(dates: Iterable[date], closes: list[tuple[date, date]]) -> list[tuple[date, date]]:
    """The closed months (start, end) that hold any of the dates."""
    days = set(dates)
    return [(s, e) for s, e in closes if any(s <= d <= e for d in days)]


def filed_hits(dates: Iterable[date], filed: set[tuple[int, int]], fye: int) -> list[tuple[int, int]]:
    """The filed (fiscal year, quarter) pairs that hold any of the dates; quarter 0 is the annual return, which holds
    the whole fiscal year."""
    out = []
    for d in sorted(set(dates)):
        p = period_for(d, fye)
        for key in ((p.fiscal_year, p.quarter), (p.fiscal_year, 0)):
            if key in filed and key not in out:
                out.append(key)
    return out


def _amount(value) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except InvalidOperation:
        return Decimal(0)


def bank_touches(entries: Iterable, bank_codes: set[str]) -> list[tuple[str, date]]:
    """(bank account, date) for every entry line on a bank account."""
    out = []
    for e in entries:
        for l in e.lines or []:
            code = str(l.get("account_code", ""))
            if code in bank_codes and (_amount(l.get("debit")) or _amount(l.get("credit"))):
                if (code, e.entry_date) not in out:
                    out.append((code, e.entry_date))
    return out


def opening_bank_delta(before: list[dict], after: list[dict], bank_codes: set[str]) -> set[str]:
    """Bank accounts whose opening balance differs between two versions of the opening entry."""
    def net(lines):
        out: dict[str, Decimal] = {}
        for l in lines or []:
            code = str(l.get("account_code", ""))
            if code in bank_codes:
                out[code] = out.get(code, Decimal(0)) + _amount(l.get("debit")) - _amount(l.get("credit"))
        return out
    old, new = net(before), net(after)
    return {c for c in set(old) | set(new) if old.get(c, Decimal(0)) != new.get(c, Decimal(0))}


def reconciled_hits(touches: Iterable[tuple[str, date]],
                    recs: list[tuple[str, date, date]]) -> list[tuple[str, date]]:
    """(account, month start) of each live reconciliation that holds a touched date (in or before its month: the
    book balance it tied carries every earlier posting)."""
    out = []
    for account, start, end in recs:
        if any(a == account and d <= end for a, d in touches) and (account, start) not in out:
            out.append((account, start))
    return out


@dataclass(frozen=True)
class UndoFacts:
    kind: str
    undone: bool
    fye: int
    opening: str = ""                                            # an opening_plan problem
    closed: list[tuple[date, date]] = field(default_factory=list)
    filed: list[tuple[int, int]] = field(default_factory=list)
    reconciled: list[tuple[str, date]] = field(default_factory=list)
    confirmed: list[str] = field(default_factory=list)           # items a confirmed bank line pays
    paid: list[str] = field(default_factory=list)                # items with a payment recorded on them
    written_off: list[str] = field(default_factory=list)         # items in a live write-off
    edited: list[str] = field(default_factory=list)              # entries edited since the import


def _names(values: list[str]) -> str:
    shown = ", ".join(v or "(no number)" for v in values[:_SHOWN])
    return shown + (f" and {len(values) - _SHOWN} more" if len(values) > _SHOWN else "")


def undo_problem(f: UndoFacts) -> str:
    """Why the batch can't be undone ("" when it can): the first blocking reason, worded for the person."""
    if f.undone:
        return "This import was already undone"
    if f.opening:
        return f.opening
    if f.closed:
        months = ", ".join(f"{s:%B %Y}" for s, _ in f.closed)
        return (f"{months} {'is' if len(f.closed) == 1 else 'are'} closed and this import posts there. Reopen the "
                "month first, or correct it with a journal entry")
    if f.filed:
        quarters = ", ".join(f"Q{q} {y}" if q else f"the FY {y} annual return" for y, q in f.filed)
        return (f"{quarters} {'is' if len(f.filed) == 1 else 'are'} marked filed and this import is in "
                f"{'its' if len(f.filed) == 1 else 'their'} books. Correct it with a journal entry instead")
    if f.reconciled:
        where = ", ".join(f"{a} for {s:%B %Y}" for a, s in f.reconciled)
        return (f"The bank reconciliation of {where} includes this import. Correct it with a journal entry instead, "
                "or change a line of that month on the Bank page (which voids the reconciliation) first")
    if f.confirmed:
        return f"A confirmed bank line is matched to {_names(f.confirmed)}; reject that match on the Bank page first"
    if f.paid:
        return f"A payment is recorded on {_names(f.paid)}; clear it first"
    if f.written_off:
        return f"{_names(f.written_off)} {'is' if len(f.written_off) == 1 else 'are'} in a write-off; delete it first"
    if f.edited:
        return (f"{_names(f.edited)} {'was' if len(f.edited) == 1 else 'were'} edited after the import; delete "
                f"{'it' if len(f.edited) == 1 else 'them'} on the Journal entries page instead, or undo the edit")
    return ""
