"""Global search: read what a person typed (amount, TIN, Philippine date formats, review reason names) and rank
the rows the router found (pure; no DB)."""

import calendar
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

MAX_QUERY = 100
MAX_TOKENS = 5
MIN_TEXT = 2

# Short names of the review reasons (classify.REVIEW_REASONS), what a person types to find them.
REASON_NAMES: dict[str, str] = {
    "low_confidence": "Low confidence",
    "missing_date": "Missing date",
    "missing_amount": "Missing amount",
    "unsorted": "Unsorted",
    "not_addressed_to_client": "Not addressed to client",
    "seller_not_vat_registered": "Seller not VAT registered",
    "not_an_invoice": "Not an invoice",
    "vat_math_mismatch": "VAT math mismatch",
    "amounts_dont_add_up": "Amounts don't add up",
    "possible_duplicate": "Possible duplicate",
    "other_company_tin": "Other company's TIN",
    "nothing_extracted": "Nothing extracted",
    "possible_payment": "Possible payment",
    "supplier_rule_mismatch": "Supplier rule mismatch",
    "tendered_less_than_total": "Tendered less than total",
    "ewt_expected": "EWT expected",
    "payment_source_unknown": "Payment source unknown",
    "payment_unverified": "Payment unverified",
    "duplicate_invoice_number": "Duplicate invoice number",
    "personal_purchase": "Personal purchase",
    "account_locked": "Account locked",
}
_STOP = frozenset({"a", "an", "the", "to", "of", "and", "than", "not", "in", "on", "for", "is"})

_MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
           "november", "december")
_MIN_YEAR, _MAX_YEAR = 1990, 2100


@dataclass
class SearchQuery:
    text: str
    tokens: list[str] = field(default_factory=list)
    amount: Decimal | None = None
    tin: str | None = None
    tin_prefix: str | None = None
    dates: list[tuple[date, date]] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    too_short: bool = False

    @property
    def structured(self) -> bool:
        return bool(self.amount is not None or self.tin or self.dates)


_CURRENCY = re.compile(r"^(?:₱|php|p)\s*", re.IGNORECASE)
_GROUPED = re.compile(r"^\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?$")
_PLAIN = re.compile(r"^\d{1,12}(?:\.\d{1,2})?$")


def parse_amount(s: str) -> Decimal | None:
    """A peso amount: "1500", "1,500.00", "₱1,500", "P1,500", "PHP 1500", "(1,500)" → 1500.00 (absolute value)."""
    s = _CURRENCY.sub("", (s or "").strip()).strip()
    if s.startswith("(") and s.endswith(")"):  # accounting negative: (1,500) or (₱1,500)
        s = _CURRENCY.sub("", s[1:-1].strip()).strip()
    s = s.lstrip("-").strip()
    if not (_GROUPED.match(s) or _PLAIN.match(s)):
        return None
    digits = s.replace(",", "")
    if len(digits.split(".")[0]) > 12:
        return None
    try:
        return Decimal(digits).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def _digits_only(s: str) -> str | None:
    s = (s or "").strip()
    return re.sub(r"[\s-]", "", s) if s and re.fullmatch(r"[\d\s-]+", s) else None


def parse_tin(s: str) -> str | None:
    """A TIN in any format: 9 digits, or 12–14 with the branch code → the 9 stored digits."""
    d = _digits_only(s)
    if d and (len(d) == 9 or 12 <= len(d) <= 14):
        return d[:9]
    return None


def _year(y: str) -> int | None:
    n = int(y)
    if len(y) == 2:
        n += 2000
    elif len(y) != 4:
        return None
    return n if _MIN_YEAR <= n <= _MAX_YEAR else None


def _day(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _month_word(w: str) -> int | None:
    w = w.lower().rstrip(".")
    if len(w) < 3:
        return None
    for i, name in enumerate(_MONTHS, start=1):
        if name.startswith(w) or (w == "sept" and i == 9):
            return i
    return None


def _month_range(y: int, m: int) -> tuple[date, date]:
    return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])


def parse_dates(s: str, today: date) -> list[tuple[date, date]]:
    """Date ranges the text can mean: one day, both readings of an ambiguous 03/04/2026 (MM/DD first, as on PH
    forms), or a whole month ("Oct 2026", "2026-10")."""
    s = re.sub(r"\s+", " ", (s or "").strip().rstrip("."))
    if m := re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", s):
        y = _year(m[1])
        d = y and _day(y, int(m[2]), int(m[3]))
        return [(d, d)] if d else []
    if m := re.fullmatch(r"(\d{4})-(\d{1,2})", s):
        y, mo = _year(m[1]), int(m[2])
        return [_month_range(y, mo)] if y and 1 <= mo <= 12 else []
    if m := re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{2}|\d{4})", s):
        y = _year(m[3])
        if not y:
            return []
        out = []
        for mo, dd in ((int(m[1]), int(m[2])), (int(m[2]), int(m[1]))):
            d = _day(y, mo, dd)
            if d and (d, d) not in out:
                out.append((d, d))
        return out
    if m := re.fullmatch(r"([A-Za-z]+\.?) (\d{1,2}),? (\d{4})", s):          # Oct 15, 2026
        mo, y = _month_word(m[1]), _year(m[3])
        d = mo and y and _day(y, mo, int(m[2]))
        return [(d, d)] if d else []
    if m := re.fullmatch(r"(\d{1,2}) ([A-Za-z]+\.?),? (\d{4})", s):          # 15 Oct 2026
        mo, y = _month_word(m[2]), _year(m[3])
        d = mo and y and _day(y, mo, int(m[1]))
        return [(d, d)] if d else []
    if m := re.fullmatch(r"([A-Za-z]+\.?),? (\d{4})", s):                    # Oct 2026
        mo, y = _month_word(m[1]), _year(m[2])
        return [_month_range(y, mo)] if mo and y else []
    return []


def match_reasons(s: str) -> list[str]:
    """Review reasons whose short name (or code) the text names: every typed word starts a word of the name."""
    raw = (s or "").strip().lower()
    if raw in REASON_NAMES:
        return [raw]
    words = [w for w in re.split(r"[\s_]+", raw) if w and w not in _STOP]
    if not words or any(len(w) < 3 for w in words):
        return []
    out = []
    for code, name in REASON_NAMES.items():
        name_words = re.split(r"[\s_']+", name.lower())
        if all(any(nw.startswith(w) for nw in name_words) for w in words):
            out.append(code)
    return out


def like_pattern(s: str) -> str:
    """A contains-pattern for ILIKE with the LIKE wildcards in the text taken literally (escape char "\\")."""
    return "%" + s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def parse_query(raw: str, today: date) -> SearchQuery:
    # Control characters never match, and a NUL in a text parameter is a Postgres error (500): drop them.
    text = re.sub(r"\s+", " ", (raw or "").strip())
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Cc")[:MAX_QUERY].strip()
    q = SearchQuery(text=text, tokens=text.split(" ")[:MAX_TOKENS] if text else [])
    q.amount = parse_amount(text)
    q.tin = parse_tin(text)
    d = _digits_only(text)
    if d and 3 <= len(d) <= 8:
        q.tin_prefix = d
    q.dates = parse_dates(text, today)
    q.reasons = match_reasons(text)
    q.too_short = len(text) < MIN_TEXT and not q.structured
    return q


def _tier(value: str, needle: str) -> int:
    if not needle or not value:
        return 0
    if value == needle:
        return 100
    if value.startswith(needle):
        return 60
    if any(w.startswith(needle) for w in re.split(r"[^0-9a-z]+", value) if w):
        return 50
    return 40 if needle in value else 0


_STRUCTURED = {"tin": 90, "amount": 70, "reason": 60, "date": 50, "tin_prefix": 45}


def score(fields: dict[str, str], q: SearchQuery, structured: set[str]) -> int:
    """Rank one row: the whole query against each field (exact 100, prefix 60, word start 50, contains 40), plus the
    average of each word's best tier, plus the best structured hit (TIN, amount, review reason, date)."""
    values = [(v or "").lower() for v in fields.values()]
    whole = q.text.lower()
    best_whole = max((_tier(v, whole) for v in values), default=0)
    tokens = [t.lower() for t in q.tokens]
    words = sum(max((_tier(v, t) for v in values), default=0) for t in tokens) / len(tokens) if tokens else 0
    return int(best_whole + words + max((_STRUCTURED.get(s, 0) for s in structured), default=0))
