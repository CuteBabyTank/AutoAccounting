"""Format spec cleaner for the Extract tab (pure).

A format is a list of fields plus a list of checks. Everything a person or the model proposes passes through here
before it is stored or shown: text is reduced to a safe alphabet, and checks are limited to the fixed catalogue
(no code, regular expressions or formulas are ever kept).
"""

import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any

Field = dict[str, Any]
Check = dict[str, Any]

TYPES = ("text", "number", "money", "date", "tin", "percent", "code", "boolean")
SCOPES = ("header", "row")
LEVELS = ("red", "yellow")
PATTERNS = ("tin", "atc", "zip")
MAX_FIELDS = 60
MAX_CHECKS = 30
MAX_KEY = 40
MAX_LABEL = 60
MAX_DESCRIPTION = 200
MAX_VALUE = 200
MAX_TERMS = 10
MAX_RATES = 6
MAX_ONE_OF = 20
MAX_NUMBER_CHARS = 30
MAX_MAGNITUDE = Decimal("1e15")
MAX_DECIMALS = 12

_PUNCT = frozenset("-/.,()%#&'")
_NUMERIC = ("money", "number", "percent")
_PATTERN_WORDS = {"tin": "a valid TIN", "atc": "an ATC code", "zip": "a valid ZIP code"}


def clean_text(value: Any, limit: int) -> str:
    """Letters (any language), digits, spaces and `- / . , ( ) % # & '`, on one line, at most `limit` characters."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return ""
    text = "".join(" " if ch.isspace() else ch for ch in str(value))
    text = "".join(ch for ch in text if ch == " " or ch.isalnum() or ch in _PUNCT)
    return " ".join(text.split())[:limit].strip()


def _key_from(label: str, taken: set[str]) -> str:
    base = re.sub(r"\W+", "_", label.lower()).strip("_")[:MAX_KEY].strip("_") or "field"
    key, n = base, 1
    while key in taken:
        n += 1
        suffix = f"_{n}"
        key = base[: MAX_KEY - len(suffix)] + suffix
    return key


def clean_fields(raw: Any) -> list[Field]:
    """Keep well-formed fields (max 60); keys come from the labels. A missing scope means a header field."""
    if not isinstance(raw, list):
        return []
    out: list[Field] = []
    taken: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        label = clean_text(item.get("label"), MAX_LABEL)
        ftype = item.get("type")
        scope = item.get("scope", "header")
        if not label or ftype not in TYPES or scope not in SCOPES:
            continue
        key = _key_from(label, taken)
        taken.add(key)
        field: Field = {
            "key": key,
            "label": label,
            "type": ftype,
            "scope": scope,
            "required": item.get("required") is True,
            "description": clean_text(item.get("description"), MAX_DESCRIPTION),
        }
        value = clean_text(item.get("value"), MAX_VALUE)
        if value:
            field["value"] = value
        out.append(field)
        if len(out) >= MAX_FIELDS:
            break
    return out


# ── checks ────────────────────────────────────────────────────────────────

def _number(value: Any) -> str | None:
    """A finite number as a normalized Decimal string, else None."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    text = str(value).strip()
    if len(text) > MAX_NUMBER_CHARS:
        return None
    try:
        d = Decimal(text)
        if not d.is_finite() or abs(d) >= MAX_MAGNITUDE:
            return None
        if d == 0:
            return "0"
        d = d.normalize()
        if d.as_tuple().exponent < -MAX_DECIMALS:
            return None
        return format(d, "f")
    except (InvalidOperation, ArithmeticError):
        return None


def _rate(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not 0 <= value <= 100:
        return None
    return int(value) if float(value).is_integer() else float(value)


class _Refs:
    """Looks up fields by key and tests their type / scope."""

    def __init__(self, fields: list[Field]):
        self.by_key = {f["key"]: f for f in fields}

    def get(self, key: Any, types: tuple[str, ...] | None = None, scope: str | None = None) -> Field | None:
        field = self.by_key.get(key) if isinstance(key, str) else None
        if field is None or (types and field["type"] not in types) or (scope and field["scope"] != scope):
            return None
        return field

    def shared_scope(self, keys: list[str]) -> str | None:
        """The one scope all these (existing) fields share, or None when they mix header and row."""
        scopes = {self.by_key[k]["scope"] for k in keys}
        return scopes.pop() if len(scopes) == 1 else None


def _params(raw: dict, refs: _Refs) -> dict | None:
    """The cleaned params of one check (without level / id), or None when it is not acceptable.

    Every kind except rows_sum (a row field summed into a header total) must use fields of a single scope.
    """
    params = _kind_params(raw, refs)
    if params is None:
        return None
    if raw["kind"] != "rows_sum" and refs.shared_scope(check_fields(params)) is None:
        return None
    return params


def _kind_params(raw: dict, refs: _Refs) -> dict | None:
    kind = raw.get("kind")
    ok = refs.get
    if kind == "required":
        return {"field": raw["field"]} if ok(raw.get("field")) else None
    if kind == "sum":
        terms = raw.get("terms")
        if not isinstance(terms, list) or not 1 <= len(terms) <= MAX_TERMS:
            return None
        out_terms = []
        for t in terms:
            if not isinstance(t, dict) or isinstance(t.get("sign"), bool) or t.get("sign") not in (1, -1):
                return None
            if not ok(t.get("field"), _NUMERIC):
                return None
            out_terms.append({"field": t["field"], "sign": int(t["sign"])})
        if not ok(raw.get("target"), _NUMERIC):
            return None
        scope = refs.shared_scope([t["field"] for t in out_terms] + [raw["target"]])
        if scope is None or raw.get("scope", scope) != scope:
            return None
        return {"terms": out_terms, "target": raw["target"], "scope": scope}
    if kind == "percent_of":
        rates = raw.get("rates")
        if not isinstance(rates, list) or not 1 <= len(rates) <= MAX_RATES:
            return None
        clean_rates = [_rate(r) for r in rates]
        if any(r is None for r in clean_rates):
            return None
        if not ok(raw.get("target"), _NUMERIC) or not ok(raw.get("base"), _NUMERIC):
            return None
        return {"target": raw["target"], "base": raw["base"], "rates": clean_rates,
                "inclusive": raw.get("inclusive") is True}
    if kind == "rows_sum":
        if not ok(raw.get("row_field"), _NUMERIC, "row") or not ok(raw.get("target"), _NUMERIC, "header"):
            return None
        return {"row_field": raw["row_field"], "target": raw["target"]}
    if kind == "row_product":
        if not all(ok(raw.get(k), _NUMERIC, "row") for k in ("a", "b", "target")):
            return None
        return {"a": raw["a"], "b": raw["b"], "target": raw["target"]}
    if kind in ("date_order", "same_quarter"):
        if not ok(raw.get("first"), ("date",)) or not ok(raw.get("last"), ("date",)) or raw["first"] == raw["last"]:
            return None
        return {"first": raw["first"], "last": raw["last"]}
    if kind == "not_future":
        return {"field": raw["field"]} if ok(raw.get("field"), ("date",)) else None
    if kind == "format":
        if raw.get("pattern") not in PATTERNS or not ok(raw.get("field"), ("tin", "text", "code")):
            return None
        return {"field": raw["field"], "pattern": raw["pattern"]}
    if kind == "one_of":
        values = raw.get("values")
        if not ok(raw.get("field")) or not isinstance(values, list):
            return None
        cleaned = list(dict.fromkeys(v for v in (clean_text(x, MAX_LABEL) for x in values) if v))[:MAX_ONE_OF]
        return {"field": raw["field"], "values": cleaned} if cleaned else None
    if kind == "range":
        if not ok(raw.get("field"), _NUMERIC):
            return None
        lo, hi = _number(raw.get("min")), _number(raw.get("max"))
        if (lo is None and raw.get("min") is not None) or (hi is None and raw.get("max") is not None):
            return None
        if lo is None and hi is None:
            return None
        if lo is not None and hi is not None and Decimal(lo) > Decimal(hi):
            return None
        return {"field": raw["field"], "min": lo, "max": hi}
    if kind == "not_more_than":
        if not ok(raw.get("field"), _NUMERIC) or not ok(raw.get("limit_field"), _NUMERIC):
            return None
        if raw["field"] == raw["limit_field"]:
            return None
        return {"field": raw["field"], "limit_field": raw["limit_field"]}
    if kind == "differs":
        if not ok(raw.get("a")) or not ok(raw.get("b")) or raw["a"] == raw["b"]:
            return None
        return {"a": raw["a"], "b": raw["b"]}
    return None


def _check_id(kind: str, params: dict) -> str:
    canonical = json.dumps({"kind": kind, **params}, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "c_" + hashlib.sha1(canonical.encode()).hexdigest()[:10]


def clean_checks(raw: Any, fields: list[Field]) -> list[Check]:
    """Keep catalogue checks whose fields exist with the right types (max 30, deduped by id)."""
    if not isinstance(raw, list):
        return []
    refs = _Refs(fields)
    out: list[Check] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        params = _params(item, refs)
        if params is None:
            continue
        kind = item["kind"]
        cid = _check_id(kind, params)
        if cid in seen:
            continue
        seen.add(cid)
        level = item.get("level") if item.get("level") in LEVELS else "red"
        out.append({"id": cid, "kind": kind, "level": level, **params})
        if len(out) >= MAX_CHECKS:
            break
    return out


def default_checks(fields: list[Field]) -> list[Check]:
    """Checks every format gets: TIN format, dates not in the future, required fields filled."""
    raw: list[dict] = []
    for f in fields:
        if f["type"] == "tin":
            raw.append({"kind": "format", "field": f["key"], "pattern": "tin"})
        if f["type"] == "date":
            raw.append({"kind": "not_future", "field": f["key"]})
        if f["required"]:
            raw.append({"kind": "required", "field": f["key"]})
    return clean_checks(raw, fields)


def check_fields(check: Check) -> list[str]:
    """Every field key a check refers to."""
    keys: list[str] = [t["field"] for t in check.get("terms", [])]
    for name in ("field", "target", "base", "row_field", "a", "b", "first", "last", "limit_field"):
        if isinstance(check.get(name), str):
            keys.append(check[name])
    return keys


def apply_picks(fields: list[Field], checks: list[Check], picks: list[dict],
                check_ids: list[str]) -> tuple[list[Field], list[Check]]:
    """Narrow a proposal to what the person ticked. Raises ValueError for a key the proposal doesn't have."""
    if not isinstance(picks, list) or not isinstance(check_ids, list):
        raise ValueError("Invalid selection")
    if not all(isinstance(i, str) for i in check_ids):
        raise ValueError("Invalid check selection")
    by_key = {f["key"]: f for f in fields}
    kept_fields: list[Field] = []
    for pick in picks:
        key = pick.get("key") if isinstance(pick, dict) else None
        if not isinstance(key, str) or key not in by_key:
            raise ValueError("Unknown field in selection")
        if any(f["key"] == key for f in kept_fields):
            continue
        base = by_key[key]
        label = clean_text(pick.get("label"), MAX_LABEL) or base["label"]
        kept_fields.append({**base, "label": label, "required": pick.get("required") is True})
    survivors = {f["key"] for f in kept_fields}
    wanted = set(check_ids)
    inherited = [c for c in checks
                 if c["kind"] != "required" and c["id"] in wanted and all(k in survivors for k in check_fields(c))]
    old_levels = {c["field"]: c["level"] for c in checks if c["kind"] == "required"}
    required = [{"kind": "required", "field": f["key"], "level": old_levels.get(f["key"], "red")}
                for f in kept_fields if f["required"]]
    return kept_fields, clean_checks(inherited + required, kept_fields)


# ── sentences ─────────────────────────────────────────────────────────────

def _num(value: int | float | str) -> str:
    return f"{value:g}" if isinstance(value, (int, float)) else str(value)


def sentence(check: Check, fields: list[Field]) -> str:
    """The check in plain words, using field labels."""
    labels = {f["key"]: f["label"] for f in fields}

    def lab(key: str) -> str:
        return labels.get(key, key)

    kind = check["kind"]
    if kind == "required":
        return f"{lab(check['field'])} is required"
    if kind == "sum":
        parts = ""
        for i, t in enumerate(check["terms"]):
            name = lab(t["field"])
            if i == 0:
                parts = name if t["sign"] == 1 else f"−{name}"
            else:
                parts += f" {'+' if t['sign'] == 1 else '−'} {name}"
        return f"{parts} should equal {lab(check['target'])}"
    if kind == "percent_of":
        rates = " or ".join(f"{_num(r)}%" for r in check["rates"])
        tail = " (the amount includes the tax)" if check.get("inclusive") else ""
        return f"{lab(check['target'])} should be {rates} of {lab(check['base'])}{tail}"
    if kind == "rows_sum":
        return f"The rows' {lab(check['row_field'])} should add up to {lab(check['target'])}"
    if kind == "row_product":
        return f"{lab(check['a'])} × {lab(check['b'])} should equal {lab(check['target'])} in each row"
    if kind == "date_order":
        return f"{lab(check['first'])} should not be after {lab(check['last'])}"
    if kind == "same_quarter":
        return f"{lab(check['first'])} and {lab(check['last'])} should be in the same quarter"
    if kind == "not_future":
        return f"{lab(check['field'])} should not be in the future"
    if kind == "format":
        return f"{lab(check['field'])} should be {_PATTERN_WORDS.get(check['pattern'], 'valid')}"
    if kind == "one_of":
        return f"{lab(check['field'])} should be one of: {', '.join(check['values'])}"
    if kind == "range":
        lo, hi = check.get("min"), check.get("max")
        name = lab(check["field"])
        if lo is not None and hi is not None:
            return f"{name} should be between {lo} and {hi}"
        return f"{name} should be at least {lo}" if lo is not None else f"{name} should be at most {hi}"
    if kind == "not_more_than":
        return f"{lab(check['field'])} should not be more than {lab(check['limit_field'])}"
    if kind == "differs":
        return f"{lab(check['a'])} and {lab(check['b'])} should be different"
    return ""
