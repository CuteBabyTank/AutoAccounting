"""Where the reader says it read each field (pure).

The reader gives `[page, x0, y0, x1, y1]` per field it filled: 0-1000 from the page's top-left, page as in its
"Page N:" label (chunk-local). We keep it as `{"page": file page, "box": [fractions]}` when it is sane, and mark a
field `{"computed": True}` when the stored value isn't what the reader read (worked out or changed by the cleaner),
so the browser never looks for it on the paper. Hints are never drawn; they only steer the browser's text match
(`frontend/src/lib/field-locate.ts`).
"""

import re
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import Any

HINT_ROWS = 20          # Extract: row hints for the first rows only (output tokens)
_SCALE = 1000
_MAX_SIDE = 600         # a box over 60% of the page in either direction isn't around one value
_MONEY = re.compile(r"-?\d[\d,]*\.?\d*|-?\.\d+")


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v)


def parse_hint(value: object, page_offset: int, first: int, last: int) -> dict | None:
    """The reader's `[page, x0, y0, x1, y1]` as a hint on a file page, or None when it isn't one we trust."""
    if not isinstance(value, list) or len(value) != 5:
        return None
    page = value[0]
    if isinstance(page, bool) or not isinstance(page, int):
        return None
    coords = [_num(v) for v in value[1:]]
    if any(c is None for c in coords):
        return None
    x0, y0, x1, y1 = coords  # type: ignore[misc]
    if not (0 <= x0 < x1 <= _SCALE and 0 <= y0 < y1 <= _SCALE):
        return None
    if x1 - x0 > _MAX_SIDE or y1 - y0 > _MAX_SIDE:
        return None
    file_page = page + page_offset
    if not first <= file_page <= last:
        return None
    return {"page": file_page, "box": [round(c / _SCALE, 4) for c in (x0, y0, x1, y1)]}


def norm(value: Any) -> str:
    """A value as compared between what was read and what is stored: an amount as its 2-decimal digits, anything
    else case-folded without punctuation or spaces."""
    text = unicodedata.normalize("NFKC", "" if value is None else str(value)).strip()
    stripped = re.sub(r"[₱$\s]|php", "", text, flags=re.IGNORECASE)
    if stripped and _MONEY.fullmatch(stripped):
        try:
            return format(Decimal(stripped.replace(",", "")).quantize(Decimal("0.01")), "f")
        except InvalidOperation:
            pass
    return "".join(ch for ch in text.casefold() if ch.isalnum())


def doc_hints(where: object, values: dict[str, str], raw_values: dict[str, str], page_offset: int, first: int,
              last: int) -> dict:
    """Hints per field key: the reader's box when the stored value is what it read, `{"computed": True}` when the
    stored value was worked out or changed, nothing for a blank field or one with no usable box."""
    boxes = where if isinstance(where, dict) else {}
    out: dict[str, dict] = {}
    for key, value in values.items():
        if not norm(value):
            continue
        raw = raw_values.get(key)
        if not norm(raw) or norm(raw) != norm(value):
            out[key] = {"computed": True}
            continue
        hint = parse_hint(boxes.get(key), page_offset, first, last)
        if hint is not None:
            out[key] = hint
    return out


def _keep(hints: dict, first: int, last: int) -> dict:
    return {k: h for k, h in hints.items()
            if isinstance(h, dict) and (h.get("computed") is True or first <= h.get("page", 0) <= last)}


def prune(hints: dict, first: int, last: int) -> dict:
    """Hints without those on pages outside `first..last` (a document's page range changed)."""
    if not isinstance(hints, dict):
        return {}
    if "header" in hints or "rows" in hints:
        rows = hints.get("rows") if isinstance(hints.get("rows"), list) else []
        return {"header": _keep(hints.get("header") or {}, first, last),
                "rows": [_keep(r, first, last) if isinstance(r, dict) else {} for r in rows]}
    return _keep(hints, first, last)
