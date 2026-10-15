"""ATC databank: a company's remembered EWT ATC per supplier and per expense account (pure).

A document's ATC comes from, in order: the document itself, the supplier's ATC in this company,
the company's default for the document's expense account, then the built-in suggestion.
Suppliers set up in another company of the firm are offered as suggestions, never applied.
"""

from dataclasses import dataclass
from datetime import date

ACCOUNT_KEY = "account:"   # prefs keys: a supplier TIN (digits) or ACCOUNT_KEY + expense account


def account_key(account: str) -> str:
    return f"{ACCOUNT_KEY}{account}"


def remembered_atc(prefs: dict[str, str], tin: str, account: str) -> tuple[str, str]:
    """(ATC, source) the company remembers for a payment: source is "supplier", "account" or ""."""
    if tin and prefs.get(tin):
        return prefs[tin], "supplier"
    if prefs.get(account_key(account)):
        return prefs[account_key(account)], "account"
    return "", ""


@dataclass(frozen=True)
class SeenSupplier:
    tin: str
    name: str
    documents: int
    last_date: date | None


@dataclass(frozen=True)
class SupplierRow:
    tin: str
    name: str
    documents: int
    ewt_atc: str
    suggestion: str = ""
    suggestion_company: str = ""


def supplier_rows(seen: list[SeenSupplier], rules: dict[str, tuple[str, str]],
                  elsewhere: dict[str, tuple[str, str]]) -> list[SupplierRow]:
    """Every supplier the company has paid or has an ATC for, with a suggestion from another company when
    this one has no ATC yet. rules / elsewhere: tin -> (ATC, supplier name / company name)."""
    by_tin = {s.tin: s for s in seen}
    rows = []
    for tin in set(by_tin) | {t for t, (atc, _) in rules.items() if atc}:
        s = by_tin.get(tin)
        atc, rule_name = rules.get(tin, ("", ""))
        suggestion, company = elsewhere.get(tin, ("", "")) if not atc else ("", "")
        rows.append(SupplierRow(tin, (s.name if s and s.name else rule_name), s.documents if s else 0, atc,
                                suggestion, company))
    return sorted(rows, key=lambda r: (r.name.upper(), r.tin))
