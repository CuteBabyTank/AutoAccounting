"""Turn one extracted document into AutoAccounting document fields (pure)."""

from dataclasses import dataclass
from decimal import Decimal

from app.services.accounting.compute.ewt import atc_info, expected_atc, rate_percent
from app.services.accounting.extraction import EXPENSE_ACCOUNTS, ExtractedDoc
from app.services.accounting.matching import NAME_MATCH_THRESHOLD, name_similarity, normalize_name
from app.services.accounting.periods import period_for
from app.services.accounting.review_rules import SOFT_REASONS, needs_review_for, payment_reasons  # noqa: F401

CATEGORIES = ("sales", "purchases", "expenses", "payroll", "2307", "support", "unsorted")
DOCUMENT_ACCOUNTS = EXPENSE_ACCOUNTS + ("sales", "2307_received", "2307_issued")
REVIEW_REASONS = (
    "low_confidence", "missing_date", "missing_amount", "unsorted", "not_addressed_to_client",
    "seller_not_vat_registered", "not_an_invoice", "vat_math_mismatch", "possible_duplicate",
    "other_company_tin", "nothing_extracted", "possible_payment", "amounts_dont_add_up", "supplier_rule_mismatch",
    "tendered_less_than_total", "ewt_expected", "payment_source_unknown", "payment_unverified",
    "duplicate_invoice_number", "personal_purchase", "account_locked",
)
_EWT_ACCOUNTS = frozenset({"rent", "professional_fees"})

LOW_CONFIDENCE = 70.0
UNSORTED_CONFIDENCE = 40.0
_ROLE_NAME_THRESHOLD = 0.6
_PURCHASE_NATURES = frozenset({"goods_for_resale", "raw_materials", "import"})
_SERVICE_ACCOUNTS = frozenset({"repairs", "professional_fees", "rent", "transportation"})
_GOODS_ACCOUNTS = frozenset({"purchases", "raw_materials", "importation", "capital_goods", "office_supplies"})
_GOODS_NATURES = frozenset({"goods_for_resale", "raw_materials", "capital_goods", "other"})
_VAT_RATE = Decimal("0.12")
_VAT_TOLERANCE = Decimal("1.00")
_ZERO = Decimal("0.00")


@dataclass(frozen=True)
class CompanyProfile:
    tin: str
    registered_name: str
    aliases: tuple[str, ...]
    vat_registered: bool
    fiscal_year_end_month: int
    is_withholding_agent: bool = False
    owner_names: tuple[str, ...] = ()     # owner / officers: a purchase in their name is personal


def _name_score(name: str, company: CompanyProfile) -> float:
    return max(name_similarity(name, n) for n in (company.registered_name, *company.aliases))


def client_role(ext: ExtractedDoc, company: CompanyProfile) -> str:
    """'seller' when the client issued the document, else 'buyer'."""
    if company.tin:
        if ext.seller.tin == company.tin:
            return "seller"
        if ext.buyer.tin == company.tin:
            return "buyer"
    seller_score = _name_score(ext.seller.name, company)
    buyer_score = _name_score(ext.buyer.name, company)
    if seller_score >= _ROLE_NAME_THRESHOLD and seller_score > buyer_score:
        return "seller"
    return "buyer"


def _category(ext: ExtractedDoc, role: str) -> str:
    if ext.kind == "other" or ext.confidence < UNSORTED_CONFIDENCE:
        return "unsorted"
    if ext.kind == "statement":  # kept as support, never computed
        return "support"
    if ext.kind == "bir2307":
        return "2307"
    if ext.kind == "payroll" or ext.nature == "payroll":
        return "payroll"
    if role == "seller":
        return "sales"
    if ext.nature in _PURCHASE_NATURES or ext.kind == "import":
        return "purchases"
    return "expenses"


def _account(ext: ExtractedDoc, category: str, role: str) -> str:
    if category == "sales":
        return "sales"
    if category == "2307":
        return "2307_received" if role == "seller" else "2307_issued"
    if category == "payroll":
        return "salaries"
    if category == "purchases":
        if ext.nature == "capital_goods":  # imported equipment is still an asset
            return "capital_goods"
        return {"raw_materials": "raw_materials", "import": "importation"}.get(ext.nature, "purchases")
    if category == "support":
        return "other"
    return ext.expense_account or "other"


def _vatable(ext: ExtractedDoc) -> Decimal:
    """VATable base; derived from the total when the document only prints VAT."""
    if ext.vatable_amount > 0 or ext.vat_amount <= 0:
        return ext.vatable_amount
    derived = ext.gross_amount - ext.vat_amount - ext.exempt_amount - ext.zero_rated_amount
    return derived if derived > 0 else _ZERO


def _vat_math_mismatch(vatable: Decimal, vat: Decimal) -> bool:
    if vat <= 0:
        return False
    return abs(vatable * _VAT_RATE - vat) > _VAT_TOLERANCE


def _money(value: Decimal) -> str:
    return str(Decimal(value).quantize(Decimal("0.01")))


def _vat_note(vatable: Decimal, vat: Decimal) -> dict:
    expected = (vatable * _VAT_RATE).quantize(Decimal("0.01"))
    return {"expected": _money(expected), "difference": _money(vat - expected)}


def _addressed(ext: ExtractedDoc, company: CompanyProfile) -> bool:
    return bool(company.tin and ext.buyer.tin == company.tin) or (
        _name_score(ext.buyer.name, company) >= NAME_MATCH_THRESHOLD
    )


def _personal(ext: ExtractedDoc, company: CompanyProfile) -> bool:
    """Bought in the owner's (or an officer's) own name rather than the company's."""
    if not ext.buyer.name or not company.owner_names or _addressed(ext, company):
        return False
    return max(name_similarity(ext.buyer.name, n) for n in company.owner_names) >= NAME_MATCH_THRESHOLD


def _tendered_short(ext: ExtractedDoc) -> bool:
    if ext.change_amount < 0:
        return True
    # "Amount received" on an OR is net of the EWT the payer withheld: that is paid in full, not short.
    due = ext.gross_amount - max(ext.withholding_amount, _ZERO)
    return ext.cash_tendered > 0 and ext.gross_amount > 0 and ext.cash_tendered < due - _VAT_TOLERANCE


def _ewt_note(ext: ExtractedDoc, account: str) -> dict | None:
    """The EWT a withholding agent should have withheld from this bill, when it shows none."""
    if account not in _EWT_ACCOUNTS or ext.withholding_amount != 0 or ext.gross_amount <= 0:
        return None
    atc = expected_atc(account, ext.seller.name, ext.seller_vat_registered)
    info = atc_info(atc)
    if info is None:
        return None
    base = ext.gross_amount - ext.vat_amount if ext.vat_amount > 0 else ext.gross_amount
    return {"atc": atc, "rate": str(rate_percent(info[1])), "base": _money(base),
            "amount": _money(base * info[1])}


def _amounts_dont_add_up(ext: ExtractedDoc, vatable: Decimal) -> bool:
    """VATable + VAT + exempt + zero-rated should equal the total; a misread digit breaks it.

    Imports are skipped: their total (landed cost) and VAT base are built differently.
    """
    if ext.kind == "import":
        return False
    parts = vatable + ext.vat_amount + ext.exempt_amount + ext.zero_rated_amount
    return parts > 0 and abs(parts - ext.gross_amount) > _VAT_TOLERANCE


def _input_vat_issues(ext: ExtractedDoc, company: CompanyProfile, vatable: Decimal) -> list[str]:
    issues: list[str] = []
    if not _addressed(ext, company):
        issues.append("not_addressed_to_client")
    if ext.kind == "import":  # VAT paid to Customs: the import entry and BOC receipt support it, not an invoice
        if _vat_math_mismatch(vatable, ext.vat_amount):
            issues.append("vat_math_mismatch")
        return issues
    if ext.seller_vat_registered is not True:
        issues.append("seller_not_vat_registered")
    if "INVOICE" not in ext.document_title.upper():
        issues.append("not_an_invoice")
    if _vat_math_mismatch(vatable, ext.vat_amount):
        issues.append("vat_math_mismatch")
    return issues


def _treatment(ext: ExtractedDoc) -> str:
    if ext.vat_amount > 0:
        return "vatable"
    if ext.zero_rated_amount > 0:
        return "zero_rated"
    if ext.exempt_amount > 0:
        return "exempt"
    return ""


def rule_conflicts(nature: str, own_account: str, rule_account: str) -> bool:
    """A supplier's remembered account that doesn't fit this document: a services account for goods (a hardware
    store's repair job remembered, then its Christmas lights), or a goods account for services."""
    if not nature or own_account == rule_account:
        return False
    if rule_account in _SERVICE_ACCOUNTS:
        return nature in _GOODS_NATURES
    if rule_account in _GOODS_ACCOUNTS:
        return nature == "services"
    return False


def document_nature(raw: dict | None) -> str:
    """The nature Gemini read for a stored document ("" when unknown)."""
    nature = (raw or {}).get("nature") if isinstance(raw, dict) else None
    return nature if isinstance(nature, str) else ""


def classify_document(
    ext: ExtractedDoc,
    company: CompanyProfile,
    rules: dict[str, tuple[str, str]],
    other_company_tins: frozenset[str],
) -> dict:
    """Field values for one ``aa_documents`` row (without ids/timestamps)."""
    role = client_role(ext, company)
    counterparty = ext.buyer if role == "seller" else ext.seller
    client_party = ext.seller if role == "seller" else ext.buyer

    category = _category(ext, role)
    account = _account(ext, category, role)
    rule = rules.get(counterparty.tin) if counterparty.tin else None
    rule_mismatch = False
    if rule and category in ("purchases", "expenses") and rule[0] in ("purchases", "expenses"):
        if rule_conflicts(ext.nature, account, rule[1]):
            rule_mismatch = True  # keep the document's own reading; a person decides
        else:
            category, account = rule

    vatable = _vatable(ext)
    reasons: list[str] = ["supplier_rule_mismatch"] if rule_mismatch else []
    if ext.confidence < LOW_CONFIDENCE:
        reasons.append("low_confidence")
    if ext.doc_date is None and category != "support":
        reasons.append("missing_date")
    if ext.gross_amount <= 0 and category != "support":
        reasons.append("missing_amount")
    if category == "unsorted":
        reasons.append("unsorted")

    treatment = _treatment(ext)
    notes: dict[str, dict] = {}
    input_vat_valid: bool | None = None
    buying = role == "buyer" and category in ("purchases", "expenses")
    if buying and company.vat_registered and ext.vat_amount > 0:
        issues = _input_vat_issues(ext, company, vatable)
        # A VAT figure that isn't 12% alone doesn't lose the input VAT: the books claim 12% of the VATable
        # amount and park the excess in "VAT difference - for review".
        input_vat_valid = not [i for i in issues if i != "vat_math_mismatch"]
        reasons.extend(issues)
        if not input_vat_valid:
            treatment = "no_input_vat"
    elif _vat_math_mismatch(vatable, ext.vat_amount):
        reasons.append("vat_math_mismatch")
    if "vat_math_mismatch" in reasons:
        notes["vat_math_mismatch"] = _vat_note(vatable, ext.vat_amount)
    excluded = False
    if buying and _personal(ext, company):
        if "not_addressed_to_client" not in reasons:
            reasons.append("not_addressed_to_client")
        reasons.append("personal_purchase")
        excluded = True   # not the company's expense; drawings by journal entry if the company paid
    if _tendered_short(ext) and category != "support":
        reasons.append("tendered_less_than_total")
        notes["tendered_less_than_total"] = {"tendered": _money(ext.cash_tendered), "total": _money(ext.gross_amount),
                                             "change": _money(ext.change_amount)}
    if buying and company.is_withholding_agent:
        ewt = _ewt_note(ext, account)
        if ewt:
            reasons.append("ewt_expected")
            notes["ewt_expected"] = ewt
    reasons += payment_reasons(category, role, {"marked_paid": ext.marked_paid, "payment_terms": ext.payment_terms})
    if _amounts_dont_add_up(ext, vatable):
        reasons.append("amounts_dont_add_up")

    party_tins = {t for t in (ext.seller.tin, ext.buyer.tin) if t}
    on_neither_side = company.tin not in party_tins and bool(party_tins & other_company_tins)
    if on_neither_side or (client_party.tin and client_party.tin != company.tin and client_party.tin in other_company_tins):
        reasons.append("other_company_tin")

    period = period_for(ext.doc_date, company.fiscal_year_end_month) if ext.doc_date else None
    return {
        "page_start": ext.page_start,
        "page_end": ext.page_end,
        "document_title": ext.document_title[:120],
        "doc_type": ext.kind,
        "category": category,
        "account": account,
        "client_role": role,
        "doc_number": ext.doc_number[:60],
        "doc_date": ext.doc_date,
        "period_year": period.fiscal_year if period else None,
        "period_quarter": period.quarter if period else None,
        "period_month": period.month_in_quarter if period else None,
        "seller_name": ext.seller.name,
        "seller_tin": ext.seller.tin,
        "seller_address": ext.seller.address,
        "seller_vat_registered": ext.seller_vat_registered,
        "buyer_name": ext.buyer.name,
        "buyer_tin": ext.buyer.tin,
        "buyer_address": ext.buyer.address,
        "gross_amount": ext.gross_amount,
        "vatable_amount": vatable,
        "vat_amount": ext.vat_amount,
        "exempt_amount": ext.exempt_amount,
        "zero_rated_amount": ext.zero_rated_amount,
        "withholding_amount": ext.withholding_amount,
        "vat_treatment": treatment,
        "input_vat_valid": input_vat_valid,
        "confidence": ext.confidence,
        "review_reasons": reasons,
        "review_notes": notes,
        "needs_review": needs_review_for(reasons),
        "excluded": excluded,
        "raw": ext.raw,
    }


def empty_document_fields(page_count: int, page_start: int = 1) -> dict:
    """Placeholder row for pages Gemini returned nothing for, so they are never lost."""
    fields = classify_document(
        ExtractedDoc(page_start=page_start, page_end=page_start + max(1, page_count) - 1, kind="other"),
        CompanyProfile("", "", (), False, 12),
        {},
        frozenset(),
    )
    fields.update(review_reasons=["nothing_extracted"], review_notes={}, needs_review=True, raw=None)
    return fields


def duplicate_key(fields: dict) -> tuple[str, str] | None:
    """(seller identity, document number); the seller's name stands in when no TIN was printed."""
    number = (fields.get("doc_number") or "").strip().upper()
    if not number:
        return None
    seller = fields.get("seller_tin") or normalize_name(fields.get("seller_name") or "")
    return seller, number


def mark_duplicate(fields: dict, seen: set[tuple[str, str]]) -> None:
    """Flag a document whose seller + document number was already filed (mutates ``seen``)."""
    key = duplicate_key(fields)
    if key is None:
        return
    if key in seen:
        fields["review_reasons"].append("possible_duplicate")
        fields["needs_review"] = needs_review_for(fields["review_reasons"])
    seen.add(key)


def mark_duplicates(rows: list[dict], seen: set[tuple[str, str]]) -> set[tuple[str, str]]:
    """Flag duplicates in one file's rows; returns the updated key set without changing ``seen``.

    The caller adopts the returned set only once the file's rows are committed, so a
    file that fails and rolls back leaves no phantom keys behind.
    """
    updated = set(seen)
    for fields in rows:
        mark_duplicate(fields, updated)
    return updated
