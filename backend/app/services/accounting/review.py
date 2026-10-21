"""Shared review decisions (pure): advisory severity, withholding suggestions and payment evidence."""
from decimal import Decimal

from app.services.accounting.compute.ewt import atc_info, is_corporate_name
from app.services.accounting.compute.money import c2

ADVISORY_REASONS = frozenset({"payment_unverified"})


def needs_review(reasons: list[str]) -> bool:
    return any(r not in ADVISORY_REASONS for r in reasons)


def ewt_suggestion(doc: dict, is_agent: bool) -> tuple[str, Decimal]:
    if not is_agent or doc.get("client_role") != "buyer" or doc.get("category") not in ("purchases", "expenses"):
        return "", Decimal("0")
    account = doc.get("account")
    corporate = is_corporate_name(doc.get("seller_name", ""))
    code = ("WC010" if corporate else "WI010") if account == "professional_fees" else (
        ("WC100" if corporate else "WI100") if account == "rent" else "")
    info = atc_info(code)
    if not info:
        return "", Decimal("0")
    base = Decimal(str(doc.get("gross_amount") or 0)) - Decimal(str(doc.get("vat_amount") or 0))
    return code, c2(base * info[1])


def payment_reasons(raw: dict | None, category: str, verified: bool) -> list[str]:
    if verified:
        return []
    raw = raw or {}
    status = str(raw.get("payment_status") or "").lower()
    terms = str(raw.get("payment_terms") or "").strip().lower()
    reasons = []
    credit_terms = bool(terms and terms not in ("cash", "due on receipt"))
    if category in ("purchases", "expenses") and (credit_terms or status in ("unpaid", "partial")):
        reasons.append("payment_unverified")
    if raw.get("payment_source_unknown") is True or category == "payroll" and status in ("released", "paid"):
        reasons.append("payment_source_unknown")
    return reasons
