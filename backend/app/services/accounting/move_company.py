"""Moving a document to another company of the firm (pure parts).

A document's side (buyer / seller), folder, account and review flags all depend on which company it belongs to, so
a move re-sorts it for the new company the way extraction would, but from the document as it stands now: dates,
numbers, parties and amounts a person typed in are kept. Company-specific links (GL sub-account, ATC, the receipt
it pays, "not a duplicate" picks, the 2307 mark) don't carry over. Some links can't be undone silently, so those
documents are refused with the step to take first.
"""

import dataclasses
import json
from dataclasses import dataclass

from app.services.accounting.classify import CompanyProfile, classify_document
from app.services.accounting.extraction import ExtractedDoc, Party, parse_extraction

# Fields the re-sort recomputes for the new company.
RESORTED_FIELDS = (
    "category", "account", "client_role", "vat_treatment", "input_vat_valid", "review_reasons", "review_notes",
    "needs_review", "excluded", "period_year", "period_quarter", "period_month",
)
# Company-specific fields cleared on the way out.
CLEARED_FIELDS = {
    "gl_account_code": "", "ewt_atc": "", "settles_document_id": None, "settles_source": "", "not_duplicate_of": [],
    "cwt_2307": {}, "period_locked": False, "reviewed": False,
}


@dataclass(frozen=True)
class MoveFacts:
    """What ties a document to its current company."""
    is_statement: bool = False
    has_asset: bool = False
    confirmed_bank_match: bool = False
    written_off: bool = False
    is_2307_for_a_sale: bool = False


def move_problem(f: MoveFacts) -> str | None:
    """Why the document can't move to another company yet (the step to take first), or None."""
    if f.is_statement:
        return "Bank statements can't move between companies. Delete it here and upload it to the right company."
    if f.has_asset:
        return "This document is in the fixed asset register. Remove the asset first, then move it."
    if f.confirmed_bank_match:
        return "A bank line is confirmed as paying this document. Unmatch it on the Bank page first, then move it."
    if f.written_off:
        return "This document is part of a write-off. Delete the write-off first, then move it."
    if f.is_2307_for_a_sale:
        return "This 2307 is marked as received for a sale. Clear that mark on the sale first, then move it."
    return None


def extracted_from_document(doc) -> ExtractedDoc:
    """The document as an extraction: what Gemini read (nature, payment terms …) overlaid with its current fields."""
    raw = doc.raw if isinstance(doc.raw, dict) else {}
    parsed = parse_extraction(json.dumps([raw], default=str)) if raw else []
    base = parsed[0] if parsed else ExtractedDoc(raw=raw)
    return dataclasses.replace(
        base,
        page_start=doc.page_start,
        page_end=doc.page_end,
        document_title=doc.document_title,
        kind=doc.doc_type,
        doc_number=doc.doc_number,
        doc_date=doc.doc_date,
        seller=Party(doc.seller_name, doc.seller_tin, base.seller.branch, doc.seller_address),
        buyer=Party(doc.buyer_name, doc.buyer_tin, base.buyer.branch, doc.buyer_address),
        seller_vat_registered=doc.seller_vat_registered,
        gross_amount=doc.gross_amount,
        vatable_amount=doc.vatable_amount,
        vat_amount=doc.vat_amount,
        exempt_amount=doc.exempt_amount,
        zero_rated_amount=doc.zero_rated_amount,
        withholding_amount=doc.withholding_amount,
        confidence=doc.confidence,
    )


def resorted_fields(doc, company: CompanyProfile, rules: dict[str, tuple[str, str]],
                    other_company_tins: frozenset[str]) -> dict:
    """The field values the document takes in the new company (re-sorted + company links cleared)."""
    fields = classify_document(extracted_from_document(doc), company, rules, other_company_tins)
    out = {name: fields[name] for name in RESORTED_FIELDS}
    out.update(CLEARED_FIELDS)
    return out
