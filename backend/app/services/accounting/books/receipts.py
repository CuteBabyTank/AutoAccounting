"""Match payment receipts (OR / collection / acknowledgement) to the invoice they pay (pure).

Since EOPT (RR 7-2024) the invoice is the primary evidence of a sale; a receipt only proves the
payment. A receipt linked to its invoice is left out of the returns and posts the cash movement.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from app.services.accounting.matching import normalize_name

WINDOW = timedelta(days=180)
TOLERANCE = Decimal("1.00")
_RECEIPT_WORDS = ("OFFICIAL RECEIPT", "COLLECTION RECEIPT", "ACKNOWLEDGEMENT RECEIPT", "ACKNOWLEDGMENT RECEIPT",
                  "PAYMENT RECEIPT", "PROVISIONAL RECEIPT")


def is_invoice(title: str, doc_type: str) -> bool:
    return doc_type == "invoice" or "INVOICE" in (title or "").upper()


def is_payment_receipt(title: str, doc_type: str) -> bool:
    upper = (title or "").upper()
    if "INVOICE" in upper:
        return False
    return doc_type == "receipt" or any(word in upper for word in _RECEIPT_WORDS)


def party_key(tin: str, name: str) -> str:
    return tin or f"NAME:{normalize_name(name or '')}"


@dataclass(frozen=True)
class DocRef:
    id: str
    party: str
    role: str                 # client_role: seller | buyer
    on: date | None
    gross: Decimal
    withholding: Decimal = Decimal("0")


@dataclass(frozen=True)
class Match:
    receipt_id: str
    invoice_id: str | None
    candidates: tuple[str, ...]


def _amount_fits(receipt: DocRef, invoice: DocRef) -> bool:
    return (abs(receipt.gross - invoice.gross) <= TOLERANCE
            or abs(receipt.gross - (invoice.gross - invoice.withholding)) <= TOLERANCE)


def candidates_for(receipt: DocRef, invoices: list[DocRef], taken: set[str]) -> list[str]:
    if receipt.on is None:
        return []
    return [i.id for i in invoices
            if i.id not in taken and i.party == receipt.party and i.role == receipt.role and i.on is not None
            and i.on <= receipt.on <= i.on + WINDOW and _amount_fits(receipt, i)]


def match_receipts(receipts: list[DocRef], invoices: list[DocRef], taken: set[str] = frozenset()) -> list[Match]:
    """Oldest receipt first; an automatically linked invoice can't be claimed by a later receipt."""
    claimed = set(taken)
    out: list[Match] = []
    for r in sorted(receipts, key=lambda r: (r.on or date.max, r.id)):
        found = candidates_for(r, invoices, claimed)
        if len(found) == 1:
            claimed.add(found[0])
            out.append(Match(r.id, found[0], ()))
        else:
            out.append(Match(r.id, None, tuple(found) if len(found) > 1 else ()))
    return out
