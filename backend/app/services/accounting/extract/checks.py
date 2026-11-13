"""Value cleaning and the check catalogue for the Extract tab (pure).

Every value comes from a model reading an untrusted document, so nothing here raises on odd input: a value that
can't be read as its type is kept as text and reported as a bad cell. Checks are the fixed catalogue in `spec`.
"""

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.services.accounting import parsing
from app.services.accounting.extract import spec
from app.services.atc_codes import lookup_atc

Values = dict[str, Any]
Flag = dict[str, Any]

CONFIDENCE_FLOOR = 70
MAX_ROWS = 500
TOLERANCE = Decimal("0.05")
YELLOW_FLOOR = Decimal("1.00")
YELLOW_RATE = Decimal("0.001")

_NUMERIC_TYPES = ("money", "number", "percent")
_PLAIN_NUMBER = re.compile(r"-?(\d+(\.\d*)?|\.\d+)")
_CURRENCY = re.compile(r"₱|php|\$|%", re.IGNORECASE)
_EXTRA_DATE_FORMATS = ("%Y/%m/%d", "%d %B %Y", "%d %b %Y", "%B %d %Y", "%b %d %Y", "%m/%d/%y")
_TRUE = frozenset({"true", "yes", "y", "1"})
_FALSE = frozenset({"false", "no", "n", "0"})
_TIN_LENGTHS = (9, 12, 13, 14)
_RANK = {"pass": 0, "yellow": 1, "red": 2}


def _tidy(value: Any) -> str:
    """The original value as one line of text, capped."""
    if value is None or isinstance(value, bool):
        return "" if value is None else str(value).lower()
    return " ".join(str(value).split())[: spec.MAX_VALUE]


def _decimal(text: str) -> Decimal | None:
    """A plain decimal string as a Decimal within the spec's magnitude, else None."""
    if len(text) > spec.MAX_VALUE or not _PLAIN_NUMBER.fullmatch(text):
        return None
    d = Decimal(text)
    return d if abs(d) < spec.MAX_MAGNITUDE else None


def _parse_number(value: Any) -> Decimal | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        text = str(value)
    elif isinstance(value, str):
        text = value.strip()
        if len(text) > spec.MAX_VALUE:
            return None
    else:
        return None
    negative = text.startswith("(") and text.endswith(")")
    text = _CURRENCY.sub("", text.strip("()")).replace(",", "").replace(" ", "")
    if text.endswith("-"):
        negative, text = True, text[:-1]
    d = _decimal(text)
    if d is None:
        return None
    return -abs(d) if negative else d


def _plain(d: Decimal, money: bool) -> str:
    if money:
        return format(d.quantize(Decimal("0.01")), "f")
    text = format(d.normalize(), "f") if d else "0"
    return text


def _parse_date(text: str) -> date | None:
    if len(text) > spec.MAX_VALUE:
        return None
    found = parsing.parse_doc_date(text)
    if found:
        return found
    for fmt in _EXTRA_DATE_FORMATS:
        try:
            parsed = datetime.strptime(text, fmt).date()
        except ValueError:
            continue
        return parsed if 2000 <= parsed.year <= 2100 else None
    return None


def clean_value(value: Any, type: str) -> tuple[str, bool]:  # noqa: A002
    """`(text, ok)`: the value as its type's plain text; blank is ("", True); unreadable keeps the cleaned original."""
    original = _tidy(value)
    if not original:
        return "", True
    if type in _NUMERIC_TYPES:
        d = _parse_number(value)
        return (_plain(d, type == "money"), True) if d is not None else (original, False)
    if type == "date":
        d = _parse_date(original)
        return (d.isoformat(), True) if d else (original, False)
    if type == "tin":
        if re.fullmatch(r"[\d\-\s.]+", original) and re.search(r"\d", original):
            return re.sub(r"\D", "", original), True
        return original, False
    if type == "boolean":
        word = original.lower()
        if word in _TRUE:
            return "true", True
        if word in _FALSE:
            return "false", True
        return original, False
    return original, True


def _clean_scope(raw: dict, fields: list[spec.Field]) -> tuple[dict[str, str], list[str]]:
    out: dict[str, str] = {}
    bad: list[str] = []
    for f in fields:
        text, ok = clean_value(raw.get(f["key"]), f["type"])
        out[f["key"]] = text
        if not ok:
            bad.append(f["key"])
    return out, bad


def clean_record(raw: Any, fields: list[spec.Field]) -> tuple[Values, list[dict]]:
    """Values for the format's fields plus the bad cells `[{"key", "row"}]`. Unknown keys are dropped."""
    raw = raw if isinstance(raw, dict) else {}
    header, bad_keys = _clean_scope(raw, [f for f in fields if f["scope"] == "header"])
    bad = [{"key": k, "row": None} for k in bad_keys]
    row_fields = [f for f in fields if f["scope"] == "row"]
    rows: list[dict[str, str]] = []
    raw_rows = raw.get("rows") if isinstance(raw.get("rows"), list) else []
    for item in raw_rows[:MAX_ROWS]:
        if not isinstance(item, dict):
            continue
        row, bad_keys = _clean_scope(item, row_fields)
        bad += [{"key": k, "row": len(rows)} for k in bad_keys]
        rows.append(row)
    return {"header": header, "rows": rows}, bad


def grade(diff: Decimal, target: Decimal) -> str:
    """"pass" within 0.05, "yellow" within the larger of 1.00 and 0.1% of the target, else "red"."""
    diff = abs(diff)
    if diff <= TOLERANCE:
        return "pass"
    return "yellow" if diff <= max(YELLOW_FLOOR, abs(target) * YELLOW_RATE) else "red"


# ── running checks ────────────────────────────────────────────────────────

class _Ctx:
    def __init__(self, values: Values, fields: list[spec.Field], today: date, bad: set[tuple[str, int | None]]):
        self.values = values
        self.fields = fields
        self.today = today
        self.bad = bad
        self.scope_of = {f["key"]: f["scope"] for f in fields}
        self.labels = {f["key"]: f["label"] for f in fields}

    def text(self, key: str, row: int | None) -> str:
        if row is None:
            return self.values["header"].get(key, "")
        return self.values["rows"][row].get(key, "")

    def usable(self, key: str, row: int | None) -> str:
        """The cell's text, or "" when it is blank or unreadable."""
        return "" if (key, row) in self.bad else self.text(key, row)

    def num(self, key: str, row: int | None) -> Decimal | None:
        text = self.usable(key, row)
        return _decimal(text) if text else None

    def day(self, key: str, row: int | None) -> date | None:
        text = self.usable(key, row)
        try:
            return date.fromisoformat(text) if text else None
        except ValueError:
            return None


def _fmt(d: Decimal) -> str:
    return f"{d:,.2f}"


def _cells(keys: list[str], row: int | None) -> list[dict]:
    return [{"key": k, "row": row} for k in keys]


def _flag(check: spec.Check, ctx: _Ctx, cells: list[dict], level: str | None = None, detail: str = "") -> Flag:
    message = spec.sentence(check, ctx.fields) + (f" ({detail})" if detail else "")
    return {"check_id": check["id"], "level": level or check["level"], "message": message, "cells": cells}


def _capped(check: spec.Check, result: str) -> str:
    """A graded difference can't be worse than the check's own level."""
    return "yellow" if check["level"] == "yellow" and result == "red" else result


def _required(check, ctx, row):
    if not ctx.text(check["field"], row).strip():
        return _flag(check, ctx, _cells([check["field"]], row))
    return None


_UNKNOWN = object()  # an operand we can't know: unreadable, or text that isn't a number


def _operand(ctx: _Ctx, key: str, row: int | None):
    """The cell's number, None when blank, or _UNKNOWN."""
    if (key, row) in ctx.bad:
        return _UNKNOWN
    if not ctx.text(key, row).strip():
        return None
    n = ctx.num(key, row)
    return _UNKNOWN if n is None else n


def _sum(check, ctx, row):
    """Blank terms count as 0 once the target and at least one term are present; unreadable cells skip."""
    keys = [t["field"] for t in check["terms"]]
    target = _operand(ctx, check["target"], row)
    nums = [_operand(ctx, k, row) for k in keys]
    if target is None or target is _UNKNOWN or any(n is _UNKNOWN for n in nums) or all(n is None for n in nums):
        return None
    total = sum((t["sign"] * n for t, n in zip(check["terms"], nums) if n is not None), Decimal(0))
    result = _capped(check, grade(total - target, target))
    if result == "pass":
        return None
    present = [k for k, n in zip(keys, nums) if n is not None]
    return _flag(check, ctx, _cells(present + [check["target"]], row), result, f"{_fmt(total)} vs {_fmt(target)}")


def _percent_of(check, ctx, row):
    base = ctx.num(check["base"], row)
    if base is None:
        return None
    target = ctx.num(check["target"], row)
    if target is None:
        if ctx.usable(check["target"], row) or 0 not in check["rates"]:
            return None
        target = Decimal(0)
    best, expected = None, Decimal(0)
    for rate in check["rates"]:
        r = Decimal(str(rate))
        want = base * r / (100 + r) if check["inclusive"] else base * r / 100
        got = grade(target - want, want)
        if best is None or _RANK[got] < _RANK[best]:
            best, expected = got, want
    result = _capped(check, best or "pass")
    if result == "pass":
        return None
    return _flag(check, ctx, _cells([check["target"]], row), result, f"{_fmt(target)} vs {_fmt(expected)}")


def _row_product(check, ctx, row):
    a, b, target = (ctx.num(check[k], row) for k in ("a", "b", "target"))
    if a is None or b is None or target is None:
        return None
    result = _capped(check, grade(a * b - target, target))
    if result == "pass":
        return None
    return _flag(check, ctx, _cells([check["a"], check["b"], check["target"]], row), result,
                 f"{_fmt(a * b)} vs {_fmt(target)}")


def _rows_sum(check, ctx, _row):
    """Rows with a blank value count as 0 once one row has a value; an unreadable cell skips the check."""
    target = _operand(ctx, check["target"], None)
    if target is None or target is _UNKNOWN:
        return None
    cells, total = [], Decimal(0)
    for i in range(len(ctx.values["rows"])):
        n = _operand(ctx, check["row_field"], i)
        if n is _UNKNOWN:
            return None
        if n is not None:
            total += n
            cells.append({"key": check["row_field"], "row": i})
    if not cells:
        return None
    result = _capped(check, grade(total - target, target))
    if result == "pass":
        return None
    return _flag(check, ctx, cells + _cells([check["target"]], None), result, f"{_fmt(total)} vs {_fmt(target)}")


def _two_dates(check, ctx, row):
    first, last = ctx.day(check["first"], row), ctx.day(check["last"], row)
    if first is None or last is None:
        return None
    if check["kind"] == "date_order":
        broken = first > last
    else:
        broken = (first.year, (first.month - 1) // 3) != (last.year, (last.month - 1) // 3)
    if not broken:
        return None
    return _flag(check, ctx, _cells([check["first"], check["last"]], row),
                 detail=f"{first.isoformat()} vs {last.isoformat()}")


def _not_future(check, ctx, row):
    day = ctx.day(check["field"], row)
    if day is None or day <= ctx.today:
        return None
    return _flag(check, ctx, _cells([check["field"]], row), detail=day.isoformat())


def _format(check, ctx, row):
    text = ctx.usable(check["field"], row)
    if not text:
        return None
    if check["pattern"] == "tin":
        digits = re.sub(r"\D", "", text)
        ok = len(digits) in _TIN_LENGTHS and len(digits) == len(re.sub(r"[\s\-.]", "", text))
    elif check["pattern"] == "zip":
        ok = re.fullmatch(r"\d{4}", text.strip()) is not None
    else:  # "WC 158", "wc-158": spaces and hyphens inside the code are ignored (lookup is case-insensitive)
        ok = lookup_atc(re.sub(r"[\s\-]", "", text)) is not None
    return None if ok else _flag(check, ctx, _cells([check["field"]], row), detail=text)


def _one_of(check, ctx, row):
    text = ctx.usable(check["field"], row)
    if not text or text.casefold() in {v.casefold() for v in check["values"]}:
        return None
    return _flag(check, ctx, _cells([check["field"]], row), detail=text)


def _range(check, ctx, row):
    n = ctx.num(check["field"], row)
    if n is None:
        return None
    lo, hi = check.get("min"), check.get("max")
    if (lo is not None and n < Decimal(lo)) or (hi is not None and n > Decimal(hi)):
        return _flag(check, ctx, _cells([check["field"]], row), detail=_fmt(n))
    return None


def _not_more_than(check, ctx, row):
    n, limit = ctx.num(check["field"], row), ctx.num(check["limit_field"], row)
    if n is None or limit is None or n <= limit:
        return None
    return _flag(check, ctx, _cells([check["field"], check["limit_field"]], row),
                 detail=f"{_fmt(n)} vs {_fmt(limit)}")


def _differs(check, ctx, row):
    a, b = ctx.usable(check["a"], row), ctx.usable(check["b"], row)
    if not a or a.casefold() != b.casefold():
        return None
    return _flag(check, ctx, _cells([check["a"], check["b"]], row), detail=a)


_KINDS = {
    "required": _required, "sum": _sum, "percent_of": _percent_of, "rows_sum": _rows_sum,
    "row_product": _row_product, "date_order": _two_dates, "same_quarter": _two_dates, "not_future": _not_future,
    "format": _format, "one_of": _one_of, "range": _range, "not_more_than": _not_more_than, "differs": _differs,
}


def _runs_per_row(check: spec.Check, ctx: _Ctx) -> bool:
    if check["kind"] == "rows_sum":
        return False
    return any(ctx.scope_of.get(k) == "row" for k in spec.check_fields(check))


def run_checks(values: Values, fields: list[spec.Field], checks: list[spec.Check], today: date,
               confidence: float | None = None, bad_cells=()) -> list[Flag]:
    """Flags for unreadable cells, then each check (row checks once per row), then a low-confidence marker."""
    bad = {(c["key"], c["row"]) for c in bad_cells}
    ctx = _Ctx(values, fields, today, bad)
    flags: list[Flag] = []
    for cell in bad_cells:
        label = ctx.labels.get(cell["key"], cell["key"])
        flags.append({"check_id": "unreadable", "level": "red", "message": f"{label} could not be read",
                      "cells": [{"key": cell["key"], "row": cell["row"]}]})
    for check in checks:
        run = _KINDS.get(check.get("kind"))
        if run is None:
            continue
        rows: list[int | None] = list(range(len(values["rows"]))) if _runs_per_row(check, ctx) else [None]
        for row in rows:
            flag = run(check, ctx, row)
            if flag:
                flags.append(flag)
    if confidence is not None and confidence < CONFIDENCE_FLOOR:
        flags.append({"check_id": "confidence", "level": "yellow",
                      "message": "The reader was not sure about this document", "cells": []})
    return flags
