"""ATC databank: a company's remembered EWT ATC per supplier and per expense account (pure).

A document's ATC comes from, in order: the document itself, the supplier's ATC in this company,
the company's default for the document's expense account, then the built-in suggestion
(``compute/atc_tree.py``). Suppliers set up in another company of the firm are offered as suggestions, never applied.
"""

from collections import Counter
from dataclasses import dataclass
from datetime import date

from app.services.accounting.compute.ewt import ATC_NONE, suggest_atc
from app.services.accounting.compute.inputs import CompanyFacts, DocLine

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
    automatic: str = ""          # what the returns use for its documents with no supplier ATC, e.g. "WC120 / WC158"
    hint: str = ""               # the decision tree's ATC (or NONE) when it differs and the supplier has no ATC
    hint_reason: str = ""


def document_pick(line: DocLine, account_default: str, company: CompanyFacts) -> str:
    """The ATC the returns use for a payment when neither it nor its supplier has one: the expense type's default,
    else the standard rules."""
    if account_default == ATC_NONE:
        return ""
    return account_default or suggest_atc(line, company)


def rank_picks(picks: list[tuple[str, str]]) -> tuple[str, str]:
    """(ATCs, reason) for a supplier from its documents' (ATC, reason) picks: the two most common ATCs, most
    common first, and the reason behind the first. ("", reason) when none of them is withheld."""
    if not picks:
        return "", ""
    counts = Counter(atc for atc, _ in picks if atc)
    if not counts:
        return "", picks[0][1]
    ranked = sorted(counts, key=lambda a: (-counts[a], a))[:2]
    reason = next(why for atc, why in picks if atc == ranked[0])
    if len(ranked) > 1:
        reason += f" ({counts[ranked[0]]} of {len(picks)} documents)"
    return " / ".join(ranked), reason


@dataclass(frozen=True)
class Automatic:
    """A supplier with no ATC of its own: what the returns use now, and what the decision tree suggests instead."""
    current: str = ""      # e.g. "WC120" or "WC120 / WC158"
    hint: str = ""         # one ATC or NONE to adopt, "" when the tree agrees with the returns
    hint_reason: str = ""


def automatic_for(current: list[str], tree: list[tuple[str, str]]) -> Automatic:
    """Compare the returns' picks with the tree's for one supplier's documents."""
    now, _ = rank_picks([(atc, "") for atc in current])
    suggested, reason = rank_picks(tree)
    top_now, top_tree = now.split(" / ")[0], suggested.split(" / ")[0]
    if top_tree == top_now:
        return Automatic(now)
    return Automatic(now, top_tree or ATC_NONE, reason)


def supplier_rows(seen: list[SeenSupplier], rules: dict[str, tuple[str, str]],
                  elsewhere: dict[str, tuple[str, str]],
                  automatic: dict[str, Automatic] | None = None) -> list[SupplierRow]:
    """Every supplier the company has paid or has an ATC for, with a suggestion from another company when
    this one has no ATC yet. rules / elsewhere: tin -> (ATC, supplier name / company name); automatic: tin ->
    ``automatic_for``."""
    by_tin = {s.tin: s for s in seen}
    rows = []
    for tin in set(by_tin) | {t for t, (atc, _) in rules.items() if atc}:
        s = by_tin.get(tin)
        atc, rule_name = rules.get(tin, ("", ""))
        suggestion, company = elsewhere.get(tin, ("", "")) if not atc else ("", "")
        auto = (automatic or {}).get(tin, Automatic())
        hint, why = (auto.hint, auto.hint_reason) if not atc else ("", "")
        rows.append(SupplierRow(tin, (s.name if s and s.name else rule_name), s.documents if s else 0, atc,
                                suggestion, company, auto.current, hint, why))
    return sorted(rows, key=lambda r: (r.name.upper(), r.tin))
