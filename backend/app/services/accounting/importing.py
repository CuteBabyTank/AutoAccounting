"""Spreadsheet import primitives (pure): amounts, date formats, column guesses and fuzzy account matching.

QBO's importers needed exact type strings, refused negative lines and asked for the date format on every file.
These helpers are deliberately tolerant: an amount can carry ₱, commas, parentheses or a CR / DR suffix; the date
format is detected from the column's values (and only asked when several formats fit every value); an account is
found by its code, then its name, then the closest name, and the person confirms the mapping before anything posts.
"""

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher

# MM/DD before DD/MM: Philippine documents use the US order, so it leads the choices when both fit.
DATE_FORMATS: tuple[str, ...] = (
    "%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%m/%d/%y", "%d/%m/%y", "%Y/%m/%d", "%m-%d-%Y", "%d-%m-%Y", "%d.%m.%Y",
    "%d-%b-%Y", "%d-%b-%y", "%d %b %Y", "%b %d, %Y", "%B %d, %Y", "%d %B %Y", "%b %d %Y",
)
DATE_LABELS = {
    "%Y-%m-%d": "YYYY-MM-DD", "%m/%d/%Y": "MM/DD/YYYY", "%d/%m/%Y": "DD/MM/YYYY", "%m/%d/%y": "MM/DD/YY",
    "%d/%m/%y": "DD/MM/YY", "%Y/%m/%d": "YYYY/MM/DD", "%m-%d-%Y": "MM-DD-YYYY", "%d-%m-%Y": "DD-MM-YYYY",
    "%d.%m.%Y": "DD.MM.YYYY", "%d-%b-%Y": "DD-Mon-YYYY", "%d-%b-%y": "DD-Mon-YY", "%d %b %Y": "DD Mon YYYY",
    "%b %d, %Y": "Mon DD, YYYY", "%B %d, %Y": "Month DD, YYYY", "%d %B %Y": "DD Month YYYY", "%b %d %Y": "Mon DD YYYY",
}
FUZZY_MIN = 0.72
ALTERNATIVE_MIN = 0.5

_ABBREVIATIONS = (
    (r"\ba ?/ ?r\b", "accounts receivable"), (r"\ba ?/ ?p\b", "accounts payable"), (r"\baccts?\b", "accounts"),
    (r"\brec(v|bl)?\b", "receivable"), (r"\bpay(bl)?\b", "payable"), (r"\bppe\b", "property and equipment"),
    (r"\bacc(um)?\.? ?dep(r|n)?\b", "accumulated depreciation"), (r"\bexp\b", "expense"),
)


def parse_amount(text: str) -> Decimal | None:
    """An amount as typed in a sheet; None when blank. Parentheses, a leading minus and a CR suffix are negative."""
    raw = str(text or "")
    if "," in raw and "." in raw and raw.rfind(",") > raw.rfind("."):   # 1.234,50: a decimal comma, not 1.2345
        raise ValueError(f"'{text}' isn't an amount (use a dot for the decimals)")
    t = raw.strip().lstrip("'").upper().replace("₱", "").replace("PHP", "").replace(",", "").replace(" ", "")
    if t in ("", "-", "–", "—"):
        return None
    sign = Decimal("1")
    if t.endswith("CR"):
        sign, t = -sign, t[:-2]
    elif t.endswith("DR"):
        t = t[:-2]
    if t.startswith("(") and t.endswith(")"):
        sign, t = -sign, t[1:-1]
    try:
        value = Decimal(t)
    except InvalidOperation:
        raise ValueError(f"'{text}' isn't an amount") from None
    if not value.is_finite():
        raise ValueError(f"'{text}' isn't an amount")
    return sign * value


def _try(text: str, fmt: str) -> date | None:
    t = text.strip()
    if fmt == "%Y-%m-%d" and re.match(r"^\d{4}-\d{2}-\d{2}[T ]", t):
        t = t[:10]   # an XLSX date cell arrives as an ISO timestamp
    try:
        return datetime.strptime(t, fmt).date()
    except ValueError:
        return None


def detect_date_format(values: list[str]) -> tuple[str | None, list[str]]:
    """(the format, every format that reads all the values). The format is None when none or several fit."""
    seen = [v.strip() for v in values if v and v.strip()]
    if not seen:
        return None, []
    fits = [fmt for fmt in DATE_FORMATS if all(_try(v, fmt) is not None for v in seen)]
    return (fits[0] if len(fits) == 1 else None), fits


def parse_date(text: str, fmt: str) -> date:
    found = _try(text, fmt)
    if found is None:
        raise ValueError(f"'{text}' isn't a date in the format {DATE_LABELS.get(fmt, fmt)}")
    return found


def norm_header(text: str) -> str:
    return re.sub(r"[^a-z0-9/ ]+", " ", str(text).lower()).strip()


def suggest_columns(headers: list[str], synonyms: tuple[tuple[str, str], ...]) -> dict[str, str]:
    """field → the header that seems to hold it (each header and field used once, synonyms checked in order)."""
    out: dict[str, str] = {}
    used: set[str] = set()
    for pattern, key in synonyms:
        if key in out:
            continue
        for header in headers:
            if header and header not in used and re.search(pattern, norm_header(header)):
                out[key] = header
                used.add(header)
                break
    return out


def norm_name(text: str) -> str:
    t = str(text or "").lower().replace("&", " and ").replace("–", "-")
    for pattern, full in _ABBREVIATIONS:
        t = re.sub(pattern, full, t)
    return " ".join(re.split(r"[^a-z0-9]+", t)).strip()


def source_key(code: str, name: str) -> str:
    """The key a person's mapping override is stored under: the row's code and normalised name."""
    return f"{str(code or '').strip()}|{norm_name(name)}"


@dataclass(frozen=True)
class AccountRef:
    code: str
    name: str
    active: bool = True
    locked: bool = False


@dataclass(frozen=True)
class AccountMatch:
    code: str | None
    how: str                      # code | name | fuzzy | none
    score: float = 0.0
    alternatives: list[str] = field(default_factory=list)


_LEADING_CODE = re.compile(r"^\s*(\d{3,10})\b[\s\-–:.]*(.*)$")


def match_account(code: str, name: str, chart: list[AccountRef]) -> AccountMatch:
    """The chart account a row means: exact code, then normalised name, then the closest name."""
    by_code = {a.code: a for a in chart}
    code = str(code or "").strip()
    name = str(name or "").strip()
    if code.endswith(".0") and code[:-2].isdigit():   # a numeric code read from Excel as a float
        code = code[:-2]
    if code in by_code:
        return AccountMatch(code, "code", 1.0)
    lead = _LEADING_CODE.match(name)
    if not code and lead and lead.group(1) in by_code:
        return AccountMatch(lead.group(1), "code", 1.0)
    target = norm_name(lead.group(2) if (lead and not code and lead.group(2)) else name)
    if not target:
        return AccountMatch(None, "none")
    exact = [a for a in chart if norm_name(a.name) == target]
    if exact:
        best = next((a for a in exact if a.active), exact[0])
        return AccountMatch(best.code, "name", 1.0)
    scored = sorted(((SequenceMatcher(None, target, norm_name(a.name)).ratio(), a.code) for a in chart),
                    key=lambda x: (-x[0], x[1]))
    alternatives = [c for s, c in scored if s >= ALTERNATIVE_MIN]
    if scored and scored[0][0] >= FUZZY_MIN:
        return AccountMatch(scored[0][1], "fuzzy", round(scored[0][0], 3), alternatives[1:4])
    return AccountMatch(None, "none", round(scored[0][0], 3) if scored else 0.0, alternatives[:3])
