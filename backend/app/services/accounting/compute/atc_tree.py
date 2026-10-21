"""Decision tree for the ATC of one payment, from what extraction read on the document (pure).

Walked top to bottom, the first branch that fits wins:

1. Government payee, taxes and licenses       -> no withholding
2. Rent (expense account or rent words)       -> WI100 / WC100
3. Professional fees (account or payee words) -> consultant 050, bookkeeping 060, insurance agent 070, broker 139,
                                                 else 010; the higher tier when the payee is VAT-registered (individual)
                                                 or the supplier withheld at the higher rate
4. Contractor's services (repairs account, or contractor words such as courier, trucking, printing, catering,
   security, janitorial), never for goods     -> WI120 / WC120
5. The rate the supplier already deducted (withholding ÷ base: 2% on services -> 120, 5/10/15% -> professional tiers)
6. Top withholding agent: goods -> 158, services -> 160
7. Otherwise                                  -> no withholding

Individual (WI) or corporate (WC) comes from the payee's name. Callers check that the client is a withholding agent
and the document is a payment first (``ewt.tree_suggestion``). The tree only suggests: the returns keep using
``ewt.suggest_atc`` until a person adopts a suggestion as the supplier's ATC.
"""

import re
from dataclasses import dataclass
from decimal import Decimal

from app.services.accounting.compute.inputs import DocLine

_CORPORATE_WORDS = frozenset({
    "INC", "INCORPORATED", "CORP", "CORPORATION", "COMPANY", "LTD", "LIMITED", "OPC", "LLC",
    "COOPERATIVE", "COOP", "PARTNERSHIP", "PARTNERS",
})
_CO_ABBREVIATION = re.compile(r"\bCO\.|&\s*CO\b")  # "Co." or "& Co"; a bare "Co" is a common surname

TWA_GOODS = frozenset({"purchases", "raw_materials", "office_supplies", "capital_goods"})
TWA_SERVICES = frozenset({"transportation", "other"})
GOODS_NATURES = frozenset({"goods_for_resale", "raw_materials", "capital_goods", "other"})
_NO_WITHHOLDING_ACCOUNTS = frozenset({"taxes_licenses", "salaries"})


def _words(*phrases: str) -> re.Pattern:
    """Whole-word match on any phrase (a trailing * allows any ending: CONSULT* = consultant, consultancy)."""
    parts = [re.escape(p[:-1]) + r"\w*" if p.endswith("*") else re.escape(p) for p in phrases]
    return re.compile(r"(?<![A-Z0-9])(?:" + "|".join(parts) + r")(?![A-Z0-9])")


_GOVERNMENT = _words(
    "GOVERNMENT", "CITY OF", "MUNICIPALITY", "MUNICIPAL", "PROVINCE OF", "PROVINCIAL", "BARANGAY", "BUREAU",
    "BIR", "SSS", "PHILHEALTH", "PAG-IBIG", "PAGIBIG", "HDMF", "LTO", "LAND TRANSPORTATION OFFICE", "DEPARTMENT OF",
    "REGISTRY OF DEEDS", "TREASURER",
)
_RENT = _words("RENT", "RENTAL*", "LEASE", "LEASING", "LESSOR")
_CONSULTANT = _words("CONSULT*", "ADVISORY")
_BOOKKEEPING = _words("BOOKKEEP*")
_INSURANCE_AGENT = _words("INSURANCE AGENT*", "INSURANCE ADJUST*")
_BROKER = _words("BROKER*", "CUSTOMS BROKER*")
_PROFESSIONAL = _words(
    "ATTY", "ATTORNEY*", "LAW OFFICE*", "LAW FIRM", "LAWYER*", "NOTARY", "NOTARIAL", "CPA", "CPAS", "AUDIT*",
    "ACCOUNTING FIRM", "ACCOUNTING OFFICE", "ARCHITECT*", "ENGR", "DR", "MD", "DMD", "DENTAL", "DENTIST*",
    "CLINIC", "PROFESSIONAL FEE*", "RETAINER*",
)
_CONTRACTOR = _words(
    "CONTRACTOR*", "CONSTRUCTION", "CONSTRUCTORS", "BUILDERS", "ENGINEERING", "TRUCKING", "HAULING", "HAULERS",
    "LOGISTICS", "FREIGHT", "CARGO", "FORWARDER*", "FORWARDING", "COURIER*", "MESSENGER*", "WAREHOUSING",
    "STEVEDORING", "ARRASTRE", "SECURITY AGENCY", "SECURITY SERVICES", "JANITORIAL", "CLEANING", "MANPOWER",
    "PEST CONTROL", "LANDSCAP*", "PRINTING", "PRINTERS", "PRINT SHOP", "ADVERTISING", "CATERING", "CATERER*",
    "AIRCON", "AIRCONDITIONING", "REPAIR*", "SERVICE CENTER", "MACHINE SHOP", "PLUMBING", "ELECTRICAL SERVICES",
    "INSTALLATION", "GARBAGE", "WASTE", "MAINTENANCE SERVICES", "SOFTWARE DEVELOPMENT", "PROGRAMMING",
)
# Professional kinds: (individual low, individual high, corporate low, corporate high) ATC numbers.
_PROFESSIONAL_KINDS = (
    (_CONSULTANT, "Management or technical consultant", ("050", "051")),
    (_BOOKKEEPING, "Bookkeeping agent", ("060", "061")),
    (_INSURANCE_AGENT, "Insurance agent", ("070", "071")),
    (_BROKER, "Broker's commission", ("139", "140")),
)
_RATES = (Decimal("0.01"), Decimal("0.02"), Decimal("0.05"), Decimal("0.10"), Decimal("0.15"))


def is_corporate_name(name: str) -> bool:
    upper = (name or "").upper()
    if _CO_ABBREVIATION.search(upper):
        return True
    return any(word in _CORPORATE_WORDS for word in re.findall(r"[A-Z]+", upper))


@dataclass(frozen=True)
class AtcDecision:
    atc: str      # "" = no withholding
    reason: str   # the branch that decided, for people


def withheld_rate(line: DocLine) -> Decimal | None:
    """The rate the supplier already deducted on the document (one of 1/2/5/10/15%), if it shows one."""
    if line.withholding <= 0:
        return None
    for base in (line.gross - line.vat if line.vat > 0 else line.gross, line.gross):
        if base <= 0:
            continue
        actual = line.withholding / base
        for rate in _RATES:
            if abs(actual - rate) <= rate * Decimal("0.05"):
                return rate
    return None


def _professional(prefix: str, line: DocLine, rate: Decimal | None, text: str, why: str) -> AtcDecision:
    label, (low, high) = "Professional fees", ("010", "011")
    for pattern, kind, codes in _PROFESSIONAL_KINDS:
        if pattern.search(text):
            label, (low, high) = kind, codes
            break
    if prefix == "WC":
        upper = rate == Decimal("0.15")
        tier = "over ₱720k" if upper else "₱720k or less"
    else:
        upper = bool(line.counterparty_vat_registered) or rate == Decimal("0.10")
        tier = "VAT-registered or over ₱3M" if upper else "₱3M or less"
    payee = "corporate" if prefix == "WC" else "individual"
    return AtcDecision(f"{prefix}{high if upper else low}", f"{label}, {payee}, {tier} ({why})")


def decide(line: DocLine, top_withholding_agent: bool) -> AtcDecision:
    """Walk the tree for one payment (see the module docstring)."""
    name = (line.counterparty_name or "").upper()
    text = f"{name} {(line.description or '').upper()}"
    corporate = is_corporate_name(line.counterparty_name)
    prefix = "WC" if corporate else "WI"
    payee = "a company" if corporate else "an individual"
    goods = line.nature in GOODS_NATURES  # e.g. parts or materials booked to repairs: not a contractor's fee
    rate = withheld_rate(line)

    if _GOVERNMENT.search(name):
        return AtcDecision("", "Government office: no withholding")
    if line.account in _NO_WITHHOLDING_ACCOUNTS:
        return AtcDecision("", "Taxes and licenses: no withholding")
    if line.account == "rent":
        return AtcDecision(f"{prefix}100", f"Rent paid to {payee}")
    if _RENT.search(text) and not goods:
        return AtcDecision(f"{prefix}100", f"Rent paid to {payee} (the document mentions rent or a lease)")
    if line.account == "professional_fees":
        return _professional(prefix, line, rate, text, "professional fees account")
    if _PROFESSIONAL.search(text) or _CONSULTANT.search(text) or _BOOKKEEPING.search(text) \
            or _INSURANCE_AGENT.search(text) or _BROKER.search(text):
        if not goods:
            return _professional(prefix, line, rate, text, "payee's name or description")
    if line.account == "repairs" and not goods:
        return AtcDecision(f"{prefix}120", f"Contractor's services (repairs) by {payee}")
    if _CONTRACTOR.search(text) and not goods:
        return AtcDecision(f"{prefix}120", f"Contractor's services by {payee} (from the name or description)")
    if rate == Decimal("0.02") and not goods:
        if top_withholding_agent:
            return AtcDecision(f"{prefix}160", f"Services from {payee}; the supplier deducted 2%")
        return AtcDecision(f"{prefix}120", f"Services from {payee}; the supplier deducted 2%")
    if rate in (Decimal("0.05"), Decimal("0.10"), Decimal("0.15")) and not goods:
        return _professional(prefix, line, rate, text, f"the supplier deducted {int(rate * 100)}%")
    if top_withholding_agent:
        if line.account in TWA_GOODS or (line.account == "repairs" and goods):
            return AtcDecision(f"{prefix}158", f"Goods bought by a top withholding agent from {payee}")
        if line.account in TWA_SERVICES:
            return AtcDecision(f"{prefix}160", f"Services bought by a top withholding agent from {payee}")
    return AtcDecision("", "No withholding expected for this kind of payment")
