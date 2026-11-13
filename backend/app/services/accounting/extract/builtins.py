"""Built-in Extract formats: BIR 2307, Receipt and Invoice (pure data).

Written as raw fields and checks, then run through the same cleaners as any firm format, so a built-in can never
hold something a firm format couldn't. Labels come from the keys (`seller_tin` → "Seller TIN").
"""

from typing import Any

from app.services.accounting.extract import spec

_UPPER = frozenset({"tin", "vat", "atc", "zip"})


def _label(key: str) -> str:
    words = [w.upper() if w in _UPPER else w for w in key.split("_")]
    return words[0][:1].upper() + words[0][1:] + "".join(f" {w}" for w in words[1:])


def _field(key: str, ftype: str, description: str, scope: str = "header", required: bool = False) -> dict:
    return {"label": _label(key), "type": ftype, "scope": scope, "required": required, "description": description}


def _build(key: str, name: str, description: str, detect_hint: str, raw_fields: list[dict],
           raw_checks: list[dict]) -> dict[str, Any]:
    fields = spec.clean_fields(raw_fields)
    checks = spec.clean_checks(raw_checks + spec.default_checks(fields), fields)
    return {"key": key, "name": name, "description": spec.clean_text(description, spec.MAX_DESCRIPTION),
            "detect_hint": spec.clean_text(detect_hint, spec.MAX_DESCRIPTION), "fields": fields, "checks": checks}


def _sum(terms: list[str], target: str) -> dict:
    return {"kind": "sum", "terms": [{"field": t, "sign": 1} for t in terms], "target": target}


# ── BIR 2307 ──────────────────────────────────────────────────────────────

_BIR2307_FIELDS = [
    _field("period_from", "date", "Part I line 1, first day of the period covered", required=True),
    _field("period_to", "date", "Part I line 1, last day of the period covered", required=True),
    _field("payee_tin", "tin", "Part I line 2, TIN of the payee who received the income", required=True),
    _field("payee_name", "text", "Part I line 3, payee's registered name"),
    _field("payee_address", "text", "Part I line 4, payee's registered address, may span several lines"),
    _field("payee_zip", "code", "Part I line 4A, payee's 4-digit ZIP code"),
    _field("payee_foreign_address", "text", "Part I line 5, payee's foreign address if any"),
    _field("payor_tin", "tin", "Part II line 6, TIN of the payor who paid and withheld the tax", required=True),
    _field("payor_name", "text", "Part II line 7, payor's registered name"),
    _field("payor_address", "text", "Part II line 8, payor's registered address, may span several lines"),
    _field("payor_zip", "code", "Part II line 8A, payor's 4-digit ZIP code"),
    _field("nature_of_payment", "text", "Part III, nature of the income payment, short (max 5 words), "
           "e.g. Purchase of goods, Professional fees, Rental", scope="row"),
    _field("atc", "code", "Part III, ATC code near the left, usually 5 letters and digits like WI010, WC010, "
           "WI100, WC158", scope="row"),
    _field("month_1", "money", "Part III, income paid in the 1st month of the quarter", scope="row"),
    _field("month_2", "money", "Part III, income paid in the 2nd month of the quarter", scope="row"),
    _field("month_3", "money", "Part III, income paid in the 3rd month of the quarter", scope="row"),
    _field("total_income", "money", "Part III, total income payment for the quarter", scope="row"),
    _field("tax_withheld", "money", "Part III, tax withheld for the quarter", scope="row"),
]

_BIR2307_CHECKS = [
    {"kind": "required", "field": "period_from"},
    {"kind": "required", "field": "period_to"},
    {"kind": "required", "field": "payee_tin"},
    {"kind": "required", "field": "payor_tin"},
    _sum(["month_1", "month_2", "month_3"], "total_income"),
    {"kind": "date_order", "first": "period_from", "last": "period_to"},
    {"kind": "same_quarter", "first": "period_from", "last": "period_to"},
    {"kind": "differs", "a": "payee_tin", "b": "payor_tin"},
    {"kind": "not_more_than", "field": "tax_withheld", "limit_field": "total_income"},
    {"kind": "format", "field": "atc", "pattern": "atc"},
    {"kind": "format", "field": "payee_zip", "pattern": "zip"},
    {"kind": "format", "field": "payor_zip", "pattern": "zip"},
    {"kind": "percent_of", "target": "tax_withheld", "base": "total_income", "rates": [1, 2, 5, 10, 15],
     "level": "yellow"},
]

# ── Receipt and Invoice ───────────────────────────────────────────────────

_RECEIPT_FIELDS = [
    _field("document_title", "text", "Title printed at the top, e.g. OFFICIAL RECEIPT, SALES INVOICE"),
    _field("receipt_number", "code", "Receipt, invoice or serial number, usually top right after No."),
    _field("date", "date", "Date of the receipt or invoice", required=True),
    _field("seller_name", "text", "Registered name of the seller who issued the document, at the top",
           required=True),
    _field("seller_tin", "tin", "Seller's TIN at the top, printed after VAT REG TIN or NON-VAT REG TIN"),
    _field("seller_address", "text", "Seller's business address at the top"),
    _field("buyer_name", "text", "Customer or buyer name, after Sold to or Received from"),
    _field("buyer_tin", "tin", "Customer or buyer TIN"),
    _field("buyer_address", "text", "Customer or buyer address"),
    _field("vatable_sales", "money", "VATable sales in the VAT breakdown box, before VAT"),
    _field("vat_amount", "money", "VAT amount (12%) in the VAT breakdown box"),
    _field("vat_exempt_sales", "money", "VAT-exempt sales in the VAT breakdown box"),
    _field("zero_rated_sales", "money", "Zero-rated sales in the VAT breakdown box"),
    _field("total_amount", "money", "Total including VAT and before any withholding tax is deducted, e.g. "
           "Total Sales (VAT Inclusive)", required=True),
    _field("withholding_tax", "money", "Withholding tax deducted, e.g. Less withholding tax"),
]

_RECEIPT_CHECKS = [
    _sum(["vatable_sales", "vat_amount", "vat_exempt_sales", "zero_rated_sales"], "total_amount"),
    {"kind": "percent_of", "target": "vat_amount", "base": "vatable_sales", "rates": [12, 0]},
    {"kind": "required", "field": "date"},
    {"kind": "required", "field": "seller_name"},
    {"kind": "required", "field": "total_amount"},
]

_INVOICE_FIELDS = _RECEIPT_FIELDS + [
    _field("due_date", "date", "Date payment is due, when printed"),
    _field("payment_terms", "text", "Payment terms as printed, e.g. Cash, Net 30, 30 days PDC"),
    _field("description", "text", "Line items table, what was sold or the service rendered", scope="row"),
    _field("quantity", "number", "Line items table, quantity", scope="row"),
    _field("unit_price", "money", "Line items table, price per unit", scope="row"),
    _field("amount", "money", "Line items table, line amount", scope="row"),
]

_INVOICE_CHECKS = _RECEIPT_CHECKS + [
    {"kind": "row_product", "a": "quantity", "b": "unit_price", "target": "amount", "level": "yellow"},
    {"kind": "date_order", "first": "date", "last": "due_date"},
]

BUILTINS: dict[str, dict[str, Any]] = {
    "bir2307": _build(
        "bir2307", "BIR 2307", "Certificate of Creditable Tax Withheld at Source",
        "BIR Form No. 2307, Certificate of Creditable Tax Withheld at Source, with Part I payee, Part II payor "
        "and a Part III income payments table by month",
        _BIR2307_FIELDS, _BIR2307_CHECKS),
    "receipt": _build(
        "receipt", "Receipt", "Official or sales receipt with a VAT breakdown",
        "A receipt (OFFICIAL RECEIPT, SALES RECEIPT, CASH RECEIPT) with the seller's name and TIN at the top "
        "and a total, usually with a VAT breakdown box",
        _RECEIPT_FIELDS, _RECEIPT_CHECKS),
    "invoice": _build(
        "invoice", "Invoice", "Sales or service invoice with line items and a VAT breakdown",
        "An invoice (SALES INVOICE, SERVICE INVOICE, CHARGE INVOICE) with the seller's name and TIN at the top, "
        "a line items table and a total with a VAT breakdown",
        _INVOICE_FIELDS, _INVOICE_CHECKS),
}
