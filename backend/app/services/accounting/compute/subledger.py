"""Customer and supplier subledgers: open items, aging and "2307 to receive" items (pure).

An open item is a sale (A/R) or a bill (A/P) with something left to collect or pay as of a date: its total, less the
tax the other side withheld (customer CWT on a sale) or the company withholds (computed EWT on a bill), less the
payments the books post for it (linked receipts, ``paid_on``, matched bank lines) dated on or before that date.
A document paid at the counter (cash terms, cash tendered) is never open. Credit memos (negative totals) show as
negative items.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from app.services.accounting.compute.books import Payment
from app.services.accounting.compute.money import ZERO, c2

BUCKETS = ("current", "1-30", "31-60", "61-90", "90+")
BUCKET_LABELS = {"current": "Current", "1-30": "1-30 days", "31-60": "31-60 days", "61-90": "61-90 days",
                 "90+": "Over 90 days"}


@dataclass(frozen=True)
class OpenDoc:
    id: str
    kind: str                       # ar | ap
    contact_key: str
    contact_name: str
    contact_tin: str
    doc_number: str
    doc_date: date
    total: Decimal                  # gross, VAT included, before withholding
    withheld: Decimal = ZERO        # customer CWT on a sale / EWT the company withholds on a bill
    paid_at_counter: bool = False
    due_date: date | None = None    # printed on the document
    terms_days: int | None = None   # printed terms ("Net 30")
    payment_unverified: bool = False
    period: tuple[int, int] | None = None   # (fiscal year, quarter)
    opening: bool = False           # an imported opening item (no document behind it)


@dataclass(frozen=True)
class OpenItem:
    doc: OpenDoc
    due: date
    paid: Decimal
    open: Decimal
    days_past_due: int
    bucket: str


@dataclass(frozen=True)
class AgingRow:
    contact_key: str
    name: str
    tin: str
    buckets: dict
    total: Decimal
    count: int
    unverified: int = 0             # bills flagged payment_unverified


@dataclass(frozen=True)
class Received2307:
    id: str
    contact_key: str
    period: tuple[int, int] | None
    amount: Decimal


@dataclass(frozen=True)
class CwtItem:
    doc_id: str
    contact_key: str
    amount: Decimal
    period: tuple[int, int] | None
    status: str                     # pending | received
    document_id: str | None
    source: str                     # auto | user | ""


def counter_paid(terms: str, cash_tendered: Decimal) -> bool:
    """Paid in full on the spot: Gemini read cash terms, or the receipt prints cash tendered."""
    return (terms or "").strip().lower() == "cash" or c2(cash_tendered or ZERO) > 0


def due_date_for(doc: OpenDoc, contact_terms_days: int | None) -> date:
    """Printed due date, then printed terms, then the contact's terms, else due on the document date."""
    if doc.due_date is not None:
        return doc.due_date
    for days in (doc.terms_days, contact_terms_days):
        if days is not None and days >= 0:
            return doc.doc_date + timedelta(days=days)
    return doc.doc_date


def bucket(days_past_due: int) -> str:
    if days_past_due <= 0:
        return "current"
    if days_past_due <= 30:
        return "1-30"
    if days_past_due <= 60:
        return "31-60"
    if days_past_due <= 90:
        return "61-90"
    return "90+"


def paid_amounts(docs: list[OpenDoc], payments: list[Payment], as_of: date) -> dict[str, Decimal]:
    """What the payments dated up to ``as_of`` paid on each document (``amount None`` = whatever was left)."""
    due = {d.id: c2(d.total - d.withheld) for d in docs}
    paid: dict[str, Decimal] = {}
    for p in sorted(payments, key=lambda p: (p.on, p.id)):
        if p.settles not in due or p.on > as_of:
            continue
        left = c2(due[p.settles] - paid.get(p.settles, ZERO))
        paid[p.settles] = c2(paid.get(p.settles, ZERO) + (c2(p.amount) if p.amount is not None else max(left, ZERO)))
    return paid


def open_items(docs: list[OpenDoc], payments: list[Payment], as_of: date,
               contact_terms: dict[str, int]) -> list[OpenItem]:
    live = [d for d in docs if d.doc_date <= as_of and not d.paid_at_counter]
    paid = paid_amounts(live, payments, as_of)
    out: list[OpenItem] = []
    for d in sorted(live, key=lambda d: (d.doc_date, d.doc_number, d.id)):
        left = c2(d.total - d.withheld - paid.get(d.id, ZERO))
        if left == 0:
            continue
        due = due_date_for(d, contact_terms.get(d.contact_key))
        days = (as_of - due).days
        out.append(OpenItem(d, due, paid.get(d.id, ZERO), left, days, bucket(days)))
    return out


def aging(items: list[OpenItem]) -> list[AgingRow]:
    """One row per contact: open balance per bucket, total, item count."""
    grouped: dict[str, list[OpenItem]] = {}
    for i in items:
        grouped.setdefault(i.doc.contact_key, []).append(i)
    rows = []
    for key, group in grouped.items():
        latest = max(group, key=lambda i: i.doc.doc_date).doc
        buckets = {b: c2(sum((i.open for i in group if i.bucket == b), ZERO)) for b in BUCKETS}
        rows.append(AgingRow(key, latest.contact_name, latest.contact_tin, buckets,
                             c2(sum((i.open for i in group), ZERO)), len(group),
                             sum(1 for i in group if i.doc.payment_unverified)))
    return sorted(rows, key=lambda r: (r.name.lower(), r.contact_key))


def aging_totals(rows: list[AgingRow]) -> dict[str, Decimal]:
    out = {b: c2(sum((r.buckets[b] for r in rows), ZERO)) for b in BUCKETS}
    out["total"] = c2(sum((r.total for r in rows), ZERO))
    return out


def cwt_items(docs: list[OpenDoc], marks: dict[str, dict], received: list[Received2307]) -> list[CwtItem]:
    """A "2307 to receive" per sale the customer withheld tax on. A 2307 from the same customer for the same fiscal
    quarter marks it received; a person's mark (``marks[doc id]``) wins over that."""
    out: list[CwtItem] = []
    for d in sorted(docs, key=lambda d: (d.doc_date, d.doc_number, d.id)):
        if d.kind != "ar" or d.withheld <= 0:
            continue
        mark = marks.get(d.id) or {}
        if mark.get("status") in ("pending", "received"):
            out.append(CwtItem(d.id, d.contact_key, d.withheld, d.period, mark["status"],
                               mark.get("document_id") or None, "user"))
            continue
        cert = next((r for r in received if r.contact_key == d.contact_key and d.period is not None
                     and r.period == d.period), None)
        out.append(CwtItem(d.id, d.contact_key, d.withheld, d.period, "received" if cert else "pending",
                           cert.id if cert else None, "auto" if cert else ""))
    return out
