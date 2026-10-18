"""Reclassify: list the postings behind an account in a date range, check where they may move, preview it (pure).

Moving changes the *classification* (a document's account override / ATC, a typed journal entry's line account),
never a generated posting: the books engine recomputes, and changes to closed months post as correcting entries on
the first day of the earliest open month (``book_close.apply_closes``).
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.services.accounting.books.chart import Chart
from app.services.accounting.compute.books import Entry
from app.services.accounting.compute.cogs import is_capital_goods
from app.services.accounting.compute.inputs import DocLine
from app.services.accounting.compute.money import ZERO, c2
from app.services.accounting.review_rules import LOCKED_REASON, needs_review_for

PNL_TYPES = frozenset({"income", "cost", "expense"})
DOCUMENT_TARGET_TYPES = frozenset({"cost", "expense"})
ATC_CATEGORIES = frozenset({"purchases", "expenses"})   # the documents an ATC (EWT) applies to
MAX_ITEMS = 500


@dataclass(frozen=True)
class Candidate:
    key: str              # document:<id> | journal_entry:<id> | the entry id (not movable)
    kind: str             # document | journal_entry | other
    source_id: str
    entry_id: str
    date: date
    book: str
    reference: str
    party: str
    particulars: str
    amount: Decimal       # net debit − credit on the account in this entry
    atc: str
    movable: bool
    why_not: str
    closed: bool
    account: str = ""     # the account listed (the one being moved from)


def document_main_account(line: DocLine, chart: Chart) -> str | None:
    """The account a purchase / expense or payroll document debits; None for anything a person can't reclassify
    (sales, 2307s, capital goods — those go through the asset register)."""
    if line.category in ("purchases", "expenses") and line.client_role == "buyer":
        return None if is_capital_goods(line) else chart.doc_account(line.account, line.gl_account)
    if line.category == "payroll":
        return chart.doc_account("salaries", line.gl_account)
    return None


def _source(entry_id: str) -> tuple[str, str] | None:
    """(kind, id) of a movable source: a document's own entry or a typed journal entry; a closed-month repost
    (``fix:<id>:new``) is followed to the entry it reposts. None for reversals and closing entries."""
    if entry_id.startswith("fix:"):
        if not entry_id.endswith(":new"):
            return None
        entry_id = entry_id[4:-4]
        return _source(entry_id) or ("other", entry_id)
    if entry_id.startswith("close:"):
        return None
    parts = entry_id.split(":")
    if parts[0] == "doc" and len(parts) == 3 and parts[2] in ("buy", "payroll"):
        return "document", parts[1]
    if parts[0] == "je" and len(parts) == 2:
        return "journal_entry", parts[1]
    return "other", entry_id


WRITEOFF = "writeoff"   # ``manual`` kind of a write-off entry when its A/R lines are the ones listed


def candidates(entries: list[Entry], chart: Chart, account: str, start: date, end: date,
               docs: dict[str, tuple[str | None, str]], manual: dict[str, str], last_closed: date | None,
               atc: str = "") -> list[Candidate]:
    """Every posting on ``account`` dated in [start, end], one row per entry, with whether it can move.

    ``docs``: document id → (its current main account, its effective ATC); ``manual``: journal entry id → kind."""
    atc = atc.strip().upper()
    out: list[Candidate] = []
    for e in sorted(entries, key=lambda e: (e.date, e.id)):
        if not (start <= e.date <= end):
            continue
        amount = c2(sum((l.debit - l.credit for l in e.lines if l.account == account), ZERO))
        if not any(l.account == account for l in e.lines):
            continue
        source = _source(e.id)
        if source is None:
            continue
        kind, sid = source
        movable, why, doc_atc = False, "", ""
        if kind == "document":
            current, doc_atc = docs.get(sid, (None, ""))
            if current is None:
                why = "This document's account can't be changed here (deleted, excluded or not an expense)."
            elif current != account:
                why = f"Already moved to {current} {chart.name(current)}."
            else:
                movable = True
        elif kind == "journal_entry":
            k = manual.get(sid)
            if k == "manual":
                movable = True
            elif k == WRITEOFF:
                why = "A write-off's A/R lines are tied to its invoices; delete the write-off and write off again."
            else:
                why = ("Opening balances are edited in Books." if k == "opening"
                       else "This journal entry no longer exists.")
        else:
            why = "Posted by the books (tax, payment, bank, depreciation or closing); change its source instead."
        if atc and (kind != "document" or doc_atc.upper() != atc):
            continue
        key = f"{kind}:{sid}" if kind != "other" else sid
        out.append(Candidate(key, kind, sid, e.id, e.date, e.book, e.reference, e.party_name, e.particulars,
                             amount, doc_atc, movable, why, last_closed is not None and e.date <= last_closed,
                             account))
    return out


def check_target(chart: Chart, source: str, target: str, kinds: set[str]) -> str:
    """"" when the selected items (of these kinds) may move from ``source`` to ``target``, else why not.
    An empty target means an ATC-only change."""
    if not target:
        return ""
    to = chart.get(target)
    if to is None:
        return f"Account {target} isn't in the chart."
    if target == source:
        return "Choose a different account to move to."
    if not to.active:
        return f"Account {target} {to.name} is inactive."
    if to.locked:
        return f"Account {target} {to.name} is locked."
    src = chart.get(source)
    if src is not None and (src.type in PNL_TYPES) != (to.type in PNL_TYPES):
        side = "Profit and loss" if src.type in PNL_TYPES else "Balance sheet"
        return f"Move within the same statement: {source} is a {side} account and {target} isn't."
    if "document" in kinds and to.type not in DOCUMENT_TARGET_TYPES:
        return "Documents can only move to a cost or expense account."
    if "document" in kinds and to.system_key and not to.system_key.startswith("doc:"):
        return f"Account {target} {to.name} is posted by the books itself; documents can't move there."
    return ""


def apply_selection(rows: list[Candidate], keys: list[str]) -> tuple[list[Candidate], list[str]]:
    """The movable rows whose key was selected (one per source), and the selected keys that can't move."""
    movable: dict[str, Candidate] = {}
    for r in rows:
        if r.movable:
            movable.setdefault(r.key, r)
    chosen, skipped, seen = [], [], set()
    for k in keys:
        if k in seen:
            continue
        seen.add(k)
        if k in movable:
            chosen.append(movable[k])
        else:
            skipped.append(k)
    return chosen, skipped


def atc_only_selection(selected: list[Candidate], atc_keys: set[str]) -> tuple[list[Candidate], list[str]]:
    """For an ATC-only move: the items that carry an ATC (``atc_keys``) and the keys of the rest."""
    return [c for c in selected if c.key in atc_keys], [c.key for c in selected if c.key not in atc_keys]


def move_document(doc, to_account: str, to_atc: str) -> None:
    """Apply a move to a document (mutates it): the account override, the ATC on purchases / expenses only, and
    ``account_locked`` dropped once the document leaves the locked account (targets are never locked)."""
    if to_account:
        doc.gl_account_code = to_account
        if LOCKED_REASON in (doc.review_reasons or []):
            doc.review_reasons = [r for r in doc.review_reasons if r != LOCKED_REASON]
            doc.needs_review = needs_review_for(doc.review_reasons)
    if to_atc and doc.category in ATC_CATEGORIES:
        doc.ewt_atc = to_atc


def move_lines(lines: list[dict], account: str, to_account: str) -> list[dict]:
    """A journal entry's lines with ``account`` replaced by ``to_account``."""
    return [dict(x, account_code=to_account) if str(x.get("account_code")) == account else x for x in lines or []]


def preview(selected: list[Candidate], chart: Chart, to_account: str, to_atc: str,
            first_open: date | None, atc_keys: set[str] | None = None) -> dict:
    """What a move would do, item by item; closed-month items post as a correction on ``first_open``.
    ``atc_keys``: the documents an ATC applies to (None = every document)."""
    to_atc = to_atc.strip().upper()
    items = []
    for c in selected:
        doc = c.kind == "document"
        takes = doc and (atc_keys is None or c.key in atc_keys)
        new_atc = to_atc if (takes and to_atc) else (c.atc if doc else "")
        items.append({
            "key": c.key, "kind": c.kind, "date": c.date, "reference": c.reference, "party": c.party,
            "amount": c.amount, "from": c.account, "to": to_account or c.account, "from_atc": c.atc,
            "to_atc": new_atc, "closed": c.closed, "posts_on": first_open if c.closed and first_open else c.date,
        })
    return {"items": items, "count": len(items), "corrections": sum(1 for c in selected if c.closed),
            "total": c2(sum((abs(c.amount) for c in selected), ZERO)),
            "to_account": to_account, "to_name": chart.name(to_account) if to_account else ""}
