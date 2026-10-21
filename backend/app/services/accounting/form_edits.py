"""Hand edits to a generated form before it is exported (pure).

A return's edits become a new version: its snapshot carries the edited figures, and ``snapshot["edited"]`` keeps the
engine's own figure for every item changed by hand (so the viewer can mark them and a later version can say they
were not carried over). Certificates (2307s, 2316s) are not versioned: their edits only shape the file exported.
"""

from decimal import Decimal, InvalidOperation

MAX_TEXT = 200


def is_amount(text: str) -> bool:
    """A stored form value that is a figure (``"10486.80"``, ``"0"``), as opposed to text or a blank."""
    if not isinstance(text, str) or not text.strip():
        return False
    try:
        return Decimal(text).is_finite()
    except InvalidOperation:
        return False


def parse_amount(text: str) -> Decimal:
    """``"1,234.50"`` / ``"(50)"`` / ``""`` → Decimal (blank is zero). ValueError when it isn't a number."""
    raw = (text or "").replace(",", "").replace("₱", "").strip()
    negative = raw.startswith("(") and raw.endswith(")")
    raw = raw.strip("()").strip() or "0"
    try:
        value = Decimal(raw)
    except InvalidOperation:
        raise ValueError(f"'{text}' isn't an amount") from None
    if not value.is_finite() or abs(value) >= Decimal("1e15"):
        raise ValueError(f"'{text}' isn't an amount")
    return -value if negative else value


def _places(text: str) -> int:
    return len(text.split(".", 1)[1]) if "." in text else 0


def clean_value(current: str, new: str) -> str:
    """The new value in the stored shape of ``current``: a figure keeps its decimal places, text is trimmed."""
    if is_amount(current):
        places = _places(current)
        value = parse_amount(new).quantize(Decimal(1).scaleb(-places))
        return format(value, "f")
    text = " ".join(str(new or "").split())
    if len(text) > MAX_TEXT:
        raise ValueError(f"Keep text under {MAX_TEXT} characters")
    return text


def apply_edits(values: dict[str, str], edits: dict[str, str], *, label: str = "item") -> dict[str, str]:
    """The keys whose value really changes → their new stored value. Unknown keys are a ValueError."""
    changed: dict[str, str] = {}
    for key, new in edits.items():
        if key not in values:
            raise ValueError(f"There is no {label} {key} on this form")
        try:
            value = clean_value(values[key], new)
        except ValueError as e:
            raise ValueError(f"{label.capitalize()} {key}: {e}") from None
        if value != values[key]:
            changed[key] = value
    return changed


def merge_edited(edited: dict[str, str], before: dict[str, str], changed: dict[str, str]) -> dict[str, str]:
    """Update a form's ``{key: engine value}`` record of hand edits. An item set back to the engine's figure drops
    out; an item edited twice keeps the engine's original figure."""
    out = dict(edited)
    for key, value in changed.items():
        engine = out.get(key, before[key])
        if value == engine:
            out.pop(key, None)
        else:
            out[key] = engine
    return out


def edits_warning(version: int, edited: dict[str, dict[str, str]]) -> str | None:
    """The version warning naming what was changed by hand."""
    parts = [f"{form} item{'s' if len(keys) > 1 else ''} {', '.join(keys)}" for form, keys in edited.items() if keys]
    if not parts:
        return None
    return (f"Edited by hand in v{version}: {'; '.join(parts)}. A version generated again from the books won't keep "
            "these edits.")


def dropped_edits_warning(previous_version: int, edited: dict[str, dict[str, str]]) -> str | None:
    """A freshly generated version after one with hand edits: say they weren't carried over."""
    parts = [f"{form} item{'s' if len(keys) > 1 else ''} {', '.join(keys)}" for form, keys in edited.items() if keys]
    if not parts:
        return None
    return (f"v{previous_version} had hand edits ({'; '.join(parts)}) that this version, generated from the books, "
            "doesn't keep. Preview the form and edit it again if they still apply.")
