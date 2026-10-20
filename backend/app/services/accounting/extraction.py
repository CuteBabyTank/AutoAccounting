"""Gemini prompts for AutoAccounting and parsing of their JSON replies (pure)."""

import json
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.ocr import clean_text
from app.services.accounting.parsing import normalize_tin, parse_doc_date, parse_money, printed_branch

KINDS = ("invoice", "receipt", "bir2307", "payroll", "import", "statement", "other")
NATURES = ("goods_for_resale", "raw_materials", "capital_goods", "services", "import", "payroll", "other")
EXPENSE_ACCOUNTS = (
    "purchases", "raw_materials", "importation", "capital_goods", "salaries", "rent",
    "utilities", "professional_fees", "office_supplies", "representation",
    "transportation", "repairs", "taxes_licenses", "other",
)

DETECT_PROMPT = """You are reading a Philippine business document (receipt, invoice, BIR form, payroll sheet, import papers).
Look at this first page and identify the two parties.

Reply with ONLY valid JSON, no markdown fences, no explanation:
{"document_title": "<title printed on the document, e.g. SALES INVOICE, OFFICIAL RECEIPT, BIR FORM 2307>",
 "kind": "<invoice|receipt|bir2307|payroll|import|statement|other>",
 "seller": {"name": "<issuer / seller / payee>", "tin": "<TIN as printed, every digit incl. the branch code>"},
 "buyer": {"name": "<customer / buyer / payor>", "tin": "<TIN as printed, every digit incl. the branch code>"},
 "date": "<document date as YYYY-MM-DD, or empty>"}

Rules:
- On a BIR Form 2307 the payee is the seller and the payor is the buyer.
- On a payroll register the employer is the buyer; leave seller empty.
- Copy a TIN with ALL its digits, including the branch code after the 9-digit number (010-234-567-000 or
  010-234-567-00000), never only the first 9. Use "" for anything not printed. Never guess a TIN."""

EXTRACT_PROMPT = """You are extracting accounting data from Philippine business documents for a bookkeeper.
The file may contain ONE or MANY separate documents (for example a scan of 40 receipts, one per page,
or one 3-page invoice). Return one entry per separate document.

Reply with ONLY valid JSON, no markdown fences, no explanation:
{"documents": [{
  "page_start": <first page of this document within this file, 1-based>,
  "page_end": <last page of this document, 1-based>,
  "document_title": "<title as printed, e.g. SALES INVOICE, OFFICIAL RECEIPT>",
  "kind": "<invoice|receipt|bir2307|payroll|import|statement|other>",
  "doc_number": "<invoice / receipt / serial number>",
  "date": "<YYYY-MM-DD>",
  "seller": {"name": "", "tin": "", "address": "", "vat_registered": <true if VAT REG TIN is printed, false if NON-VAT REG TIN, null if unclear>},
  "buyer": {"name": "", "tin": "", "address": ""},
  "gross_amount": <total INCLUDING VAT and BEFORE any withholding tax is deducted (e.g. "Total Sales (VAT Inclusive)"); when the document prints "Less: withholding tax", use the amount before that line, not the net amount due>,
  "vatable_amount": <VATable sales or purchase>,
  "vat_amount": <12% VAT shown>,
  "exempt_amount": <VAT-exempt amount>,
  "zero_rated_amount": <zero-rated amount>,
  "withholding_amount": <withholding tax deducted>,
  "cash_tendered": <cash tendered / amount received printed on a cash receipt, 0 when not shown>,
  "change": <change printed on the receipt exactly as shown, negative if it shows a negative change, 0 when not shown>,
  "payment_terms": "<credit if the document shows credit terms, a due date, PDC, charge or a balance still due; cash if paid in full on the spot; empty if unclear>",
  "due_date": "<YYYY-MM-DD when a due date is printed, else empty>",
  "terms_days": <number of days of credit when terms are printed (e.g. Net 30 or 30 days PDC = 30), else null>,
  "marked_paid": <true when the document says PAID, RELEASED or RECEIVED (e.g. a payroll sheet marked released), else false>,
  "nature": "<goods_for_resale|raw_materials|capital_goods|services|import|payroll|other>",
  "expense_account": "<purchases|raw_materials|importation|capital_goods|salaries|rent|utilities|professional_fees|office_supplies|representation|transportation|repairs|taxes_licenses|other>",
  "confidence": <0-100, your certainty in the amounts and date>,
  "statement": <ONLY for a bank or e-wallet statement, else omit: {"bank_name": "", "account_number": "<as printed>",
    "period_start": "<YYYY-MM-DD>", "period_end": "<YYYY-MM-DD>", "opening_balance": <beginning balance>,
    "closing_balance": <ending balance>,
    "lines": [{"date": "<YYYY-MM-DD>", "description": "<narration exactly as printed>", "debit": <withdrawal / money out, 0 if none>,
               "credit": <deposit / money in, 0 if none>, "balance": <running balance as printed, or "" if not shown>,
               "ref": "<check or reference number, or "">", "page": <page of this file the line is printed on, 1-based>}]}>
}]}

Rules:
- kind "statement" is for supporting papers that record no sale or purchase by themselves: bank or e-wallet
  statements, statements of account, quotations, purchase orders, delivery receipts. "other" is anything unreadable
  or not a business document.
- nature, from the point of view of the business that BOUGHT (see the client below when given):
  goods_for_resale = merchandise it sells on; raw_materials = materials that go into products it makes;
  capital_goods = equipment, machinery, vehicles, furniture or computers it will use for more than a year;
  services = work done for it; other = supplies and other things it uses up.
- On a BIR Form 2307 the payee is the seller and the payor is the buyer; gross_amount is the total income payment and withholding_amount the total tax withheld.
- On a payroll register the employer is the buyer; gross_amount is total gross pay and withholding_amount total tax withheld.
- Meals or entertainment with clients use expense_account "representation".
- Every page that carries its own complete document (its own header, number and total) is a separate entry, even when it
  repeats a document already in this file (a second copy or a rescan). Only merge pages that continue one document.
- For a bank statement list every transaction line in order, across all its pages, in "statement".lines.
- Amounts are plain numbers without currency symbols; use 0 when not shown.
- Copy a TIN with ALL its digits as printed, including the branch code after the 9-digit number (e.g.
  "010-234-567-000" or "010-234-567-00000"). Never stop at the first 9 digits and never add a branch code that
  isn't printed.
- Use "" for text that is not printed. Never invent a TIN or a document number."""


_BUSINESS = {
    "trading": "a trading business (it buys goods and resells them)",
    "manufacturing": "a manufacturer (it buys materials and makes products)",
    "services": "a services business (it sells services, not goods)",
}


def extract_prompt(client_name: str, client_tin: str, business_type: str) -> str:
    """EXTRACT_PROMPT plus who the client is, so purchases are judged from the client's side."""
    tin = f" (TIN {client_tin})" if client_tin else ""
    what = _BUSINESS.get(business_type, "a business")
    return (f"{EXTRACT_PROMPT}\n\nThe client is {client_name}{tin}, {what}. Documents it issued are its sales; "
            f"documents addressed to it are its purchases and expenses. Judge nature and expense_account for "
            f"{client_name}: goods it resells are goods_for_resale only if it is a trading business, materials "
            f"are raw_materials only if it manufactures, and anything else it buys is an expense.")


@dataclass(frozen=True)
class Party:
    name: str = ""
    tin: str = ""          # 9-digit base, "" when unknown
    branch: str = "00000"
    address: str = ""
    # The branch digits as printed ("000" stays "000"), "" when none: display only, so not part of equality.
    printed_branch: str = field(default="", compare=False)


@dataclass(frozen=True)
class Detection:
    document_title: str
    kind: str
    seller: Party
    buyer: Party
    doc_date: date | None


@dataclass
class ExtractedDoc:
    page_start: int = 1
    page_end: int = 1
    document_title: str = ""
    kind: str = "other"
    doc_number: str = ""
    doc_date: date | None = None
    seller: Party = field(default_factory=Party)
    buyer: Party = field(default_factory=Party)
    seller_vat_registered: bool | None = None
    gross_amount: Decimal = Decimal("0.00")
    vatable_amount: Decimal = Decimal("0.00")
    vat_amount: Decimal = Decimal("0.00")
    exempt_amount: Decimal = Decimal("0.00")
    zero_rated_amount: Decimal = Decimal("0.00")
    withholding_amount: Decimal = Decimal("0.00")
    nature: str = "other"
    expense_account: str = "other"
    confidence: float = 0.0
    cash_tendered: Decimal = Decimal("0.00")
    change_amount: Decimal = Decimal("0.00")   # negative when the receipt shows negative change
    payment_terms: str = ""                    # cash | credit | "" (unclear / not read)
    marked_paid: bool = False
    due_date: date | None = None
    terms_days: int | None = None              # printed credit terms in days ("Net 30")
    raw: dict = field(default_factory=dict)


def _load_json(raw: str):
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def _text(value, limit: int) -> str:
    return clean_text(str(value or ""))[:limit]


def _party(obj) -> Party:
    if not isinstance(obj, dict):
        return Party()
    tin, branch = normalize_tin(str(obj.get("tin") or ""))
    return Party(
        name=_text(obj.get("name"), 255),
        tin=tin,
        branch=branch or "00000",
        printed_branch=printed_branch(str(obj.get("tin") or "")) if tin else "",
        address=_text(obj.get("address"), 500),
    )


def _choice(value, allowed: tuple[str, ...]) -> str:
    text = str(value or "").strip().lower()
    return text if text in allowed else "other"


def _bool_or_none(value) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return value.strip().lower() == "true"
    return None


def _int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _signed_money(value) -> Decimal:
    """parse_money, keeping a leading minus sign on text amounts ("-60.00")."""
    amount = parse_money(value)
    if isinstance(value, str) and value.strip().startswith("-") and amount > 0:
        return -amount
    return amount


def _terms(value) -> str:
    text = str(value or "").strip().lower()
    return text if text in ("cash", "credit") else ""


def _terms_days(value) -> int | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        days = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return days if 0 <= days <= 3650 else None


def due_fields(raw: dict | None) -> tuple[date | None, int | None]:
    """(printed due date, printed terms in days) from a document's stored reply; old replies give (None, None)."""
    if not isinstance(raw, dict):
        return None, None
    due = parse_doc_date(raw.get("due_date")) if raw.get("due_date") else None
    return due, _terms_days(raw.get("terms_days"))


def parse_detection(raw: str) -> Detection:
    """Parse the first-page detection reply. Never raises."""
    data = _load_json(raw)
    if not isinstance(data, dict):
        data = {}
    return Detection(
        document_title=_text(data.get("document_title"), 120),
        kind=_choice(data.get("kind"), KINDS),
        seller=_party(data.get("seller")),
        buyer=_party(data.get("buyer")),
        doc_date=parse_doc_date(data.get("date")),
    )


def parse_extraction(raw: str, page_offset: int = 0, chunk_pages: int | None = None) -> list[ExtractedDoc]:
    """Parse the extraction reply into documents with 1-based file-global pages. Never raises."""
    data = _load_json(raw)
    items = data.get("documents") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return []
    last_page = chunk_pages if chunk_pages and chunk_pages > 0 else None
    docs: list[ExtractedDoc] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        start = max(1, _int(item.get("page_start"), 1))
        end = max(start, _int(item.get("page_end"), start))
        if last_page is not None:
            start = min(start, last_page)
            end = min(max(end, start), last_page)
        try:
            confidence = float(item.get("confidence") or 0)
        except (TypeError, ValueError):
            confidence = 0.0
        seller_obj = item.get("seller") if isinstance(item.get("seller"), dict) else {}
        docs.append(ExtractedDoc(
            page_start=start + page_offset,
            page_end=end + page_offset,
            document_title=_text(item.get("document_title"), 120),
            kind=_choice(item.get("kind"), KINDS),
            doc_number=_text(item.get("doc_number"), 60),
            doc_date=parse_doc_date(item.get("date")),
            seller=_party(item.get("seller")),
            buyer=_party(item.get("buyer")),
            seller_vat_registered=_bool_or_none(seller_obj.get("vat_registered")),
            gross_amount=parse_money(item.get("gross_amount")),
            vatable_amount=parse_money(item.get("vatable_amount")),
            vat_amount=parse_money(item.get("vat_amount")),
            exempt_amount=parse_money(item.get("exempt_amount")),
            zero_rated_amount=parse_money(item.get("zero_rated_amount")),
            withholding_amount=parse_money(item.get("withholding_amount")),
            nature=_choice(item.get("nature"), NATURES),
            expense_account=_choice(item.get("expense_account"), EXPENSE_ACCOUNTS),
            confidence=min(100.0, max(0.0, confidence)),
            cash_tendered=max(parse_money(item.get("cash_tendered")), Decimal("0.00")),
            change_amount=_signed_money(item.get("change")),
            payment_terms=_terms(item.get("payment_terms")),
            marked_paid=_bool_or_none(item.get("marked_paid")) is True,
            due_date=due_fields(item)[0],
            terms_days=due_fields(item)[1],
            raw=item,
        ))
    return docs
