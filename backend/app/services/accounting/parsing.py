"""Value normalisers for AutoAccounting extraction output (pure)."""

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from app.ocr import clean_amount

_CENT = Decimal("0.01")
_ZERO = Decimal("0.00")
# Largest value NUMERIC(14,2) can hold; anything bigger is a misread (e.g. a serial number).
_MAX_AMOUNT = Decimal("999999999999.99")
_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%B %d, %Y", "%b %d, %Y")


def normalize_tin(text: str | None) -> tuple[str, str]:
    """Split a printed TIN into (9-digit base, 5-digit branch code).

    Returns ("", "") when fewer than 9 digits are present. Old 3-digit branch
    codes ("000") are zero-padded to the current 5-digit form.
    """
    digits = re.sub(r"\D", "", text or "")
    if len(digits) < 9:
        return "", ""
    branch = digits[9:14].zfill(5) if len(digits) > 9 else "00000"
    return digits[:9], branch


def printed_branch(text: str | None) -> str:
    """The branch code digits exactly as printed after the 9-digit TIN ("010-234-567-000" → "000"), "" when none."""
    digits = re.sub(r"\D", "", text or "")
    return digits[9:14] if len(digits) > 9 else ""


def parse_money(value) -> Decimal:
    """Parse an amount from Gemini JSON (number or text) into a 2-dp Decimal."""
    if value is None or isinstance(value, bool):
        return _ZERO
    try:
        if isinstance(value, (int, float, Decimal)):
            amount = Decimal(str(value))
            negative = False
        else:
            text = str(value)
            negative = "(" in text and ")" in text
            amount = Decimal(clean_amount(text).replace(",", ""))
        if not amount.is_finite() or abs(amount) > _MAX_AMOUNT:
            return _ZERO
        amount = amount.quantize(_CENT)
        return -abs(amount) if negative else amount
    except (InvalidOperation, ValueError):
        return _ZERO


def parse_doc_date(value) -> date | None:
    """Parse a document date; None if unreadable or outside 2000–2100."""
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    for fmt in _DATE_FORMATS:
        try:
            parsed = datetime.strptime(text, fmt).date()
        except ValueError:
            continue
        return parsed if 2000 <= parsed.year <= 2100 else None
    return None
