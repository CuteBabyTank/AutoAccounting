"""Closed months: frozen entries, correcting entries for later changes, and final entry numbers (pure).

Closing a month freezes its entries as posted then, with final entry numbers. Every later Generate recomputes all
entries and compares each closed month's frozen entries with the recomputed ones (by id): an unchanged entry keeps
its frozen form; a changed or removed one is reversed, and a changed or late one posted, on the first day of the
earliest open month in the General Journal. Printed pages of a closed month never change.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from app.services.accounting.compute.books import Entry, Line
from app.services.accounting.compute.money import c2


@dataclass(frozen=True)
class ClosedMonth:
    start: date
    end: date
    entries: tuple[Entry, ...]          # frozen as closed
    numbers: tuple[tuple[str, str], ...]  # (entry id, final entry number)


def entry_to_json(e: Entry) -> dict:
    return {"id": e.id, "date": e.date.isoformat(), "book": e.book, "reference": e.reference,
            "party_name": e.party_name, "party_tin": e.party_tin, "particulars": e.particulars, "source": e.source,
            "lines": [[l.account, str(l.debit), str(l.credit), l.party_name, l.party_tin] for l in e.lines],
            "meta": [[k, str(v)] for k, v in e.meta]}


def entry_from_json(d: dict) -> Entry:
    return Entry(d["id"], date.fromisoformat(d["date"]), d["book"], d["reference"], d["party_name"], d["party_tin"],
                 d["particulars"], d["source"],
                 tuple(Line(a, Decimal(dr), Decimal(cr), pn, pt) for a, dr, cr, pn, pt in d["lines"]),
                 tuple((k, Decimal(v)) for k, v in d.get("meta", [])))


def _same(a: Entry, b: Entry) -> bool:
    return (a.date, a.book, a.reference, a.party_name, a.party_tin, sorted(a.lines, key=repr)) == \
        (b.date, b.book, b.reference, b.party_name, b.party_tin, sorted(b.lines, key=repr))


def _reverse(e: Entry, on: date, month: str) -> Entry:
    lines = tuple(Line(l.account, l.credit, l.debit, l.party_name, l.party_tin) for l in e.lines)
    return Entry(f"fix:{e.id}:rev", on, "GJ", e.reference, e.party_name, e.party_tin,
                 f"Reversal of {e.book} {e.reference} ({month}): {e.particulars}"[:250], "correction", lines)


def _repost(e: Entry, on: date, month: str, late: bool) -> Entry:
    text = (f"Late recording of {e.reference or e.particulars} dated {e.date:%b %-d, %Y}" if late
            else f"Correction of {e.book} {e.reference} ({month}): {e.particulars}")
    return Entry(f"fix:{e.id}:new", on, "GJ", e.reference, e.party_name, e.party_tin, text[:250], "correction",
                 e.lines, e.meta)


def apply_closes(entries: list[Entry], closes: list[ClosedMonth]) -> tuple[list[Entry], list[str]]:
    """Recomputed entries with closed months replaced by their frozen entries, plus correcting entries."""
    if not closes:
        return entries, []
    closes = sorted(closes, key=lambda c: c.start)
    first_open = closes[-1].end + timedelta(days=1)

    def closed(d: date) -> ClosedMonth | None:
        return next((c for c in closes if c.start <= d <= c.end), None)

    frozen = {e.id: (e, c) for c in closes for e in c.entries}
    out: list[Entry] = [e for c in closes for e in c.entries]
    corrections: dict[str, int] = {}
    seen: set[str] = set()
    for e in entries:
        if e.date > closes[-1].end and e.id not in frozen:  # an open month, never closed before
            out.append(e)
            continue
        seen.add(e.id)
        hit = frozen.get(e.id)
        if hit is not None:
            old, month = hit
            if _same(old, e):
                continue
            label = f"{month.start:%b %Y}"
            out += [_reverse(old, first_open, label), _repost(e, first_open, label, late=False)]
            corrections[label] = corrections.get(label, 0) + 2
            continue
        month = closed(e.date)
        if month is None:  # dated before the first close (before the books' first closed month): keep as is
            out.append(e)
            continue
        label = f"{month.start:%b %Y}"
        out.append(_repost(e, first_open, label, late=True))
        corrections[label] = corrections.get(label, 0) + 1
    for entry_id, (old, month) in frozen.items():
        if entry_id not in seen:
            label = f"{month.start:%b %Y}"
            out.append(_reverse(old, first_open, label))
            corrections[label] = corrections.get(label, 0) + 1
    warnings = []
    if corrections:
        months = ", ".join(f"{label} ({n})" for label, n in corrections.items())
        warnings.append(f"Changes to closed months were posted as correcting entries on {first_open:%b %-d, %Y}: "
                        f"{months}. Closed pages stay as printed.")
    return out, warnings


def final_numbers(month_entries: list[Entry], fiscal_year: int, used: dict[str, int]) -> dict[str, str]:
    """Final entry numbers for a month being closed, continuing each book's sequence for the fiscal year."""
    out: dict[str, str] = {}
    for e in month_entries:
        used[e.book] = used.get(e.book, 0) + 1
        out[e.id] = f"{e.book}-{fiscal_year}-{used[e.book]:04d}"
    return out


def balanced(entries: list[Entry]) -> bool:
    return all(c2(sum((l.debit for l in e.lines), Decimal(0))) == c2(sum((l.credit for l in e.lines), Decimal(0)))
               for e in entries)
