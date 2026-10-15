"""Per-form filing state stored on a period as {form: {output_id, version, filed_at, paid_on?}} (pure)."""

from collections.abc import Iterable
from datetime import date, datetime


def set_form(filed: dict, form: str, output_id: str, version: int, now: datetime,
             paid_on: date | None = None) -> dict:
    entry = {"output_id": output_id, "version": version, "filed_at": now.isoformat()}
    if paid_on is not None:  # the day the return was filed and paid (books post the payment on it)
        entry["paid_on"] = paid_on.isoformat()
    return {**filed, form: entry}


def unset_form(filed: dict, form: str) -> dict:
    return {key: value for key, value in filed.items() if key != form}


def backfill(expected: list[str], output_id: str, version: int, filed_at: datetime,
             available: Iterable[str] | None = None) -> dict:
    """A quarter marked filed before per-form filing existed: every expected form that version had went in."""
    had = set(expected if available is None else available)
    filed: dict = {}
    for form in expected:
        if form in had:
            filed = set_form(filed, form, output_id, version, filed_at)
    return filed


def file_all(filed: dict, forms: list[str], output_id: str, version: int, now: datetime,
             paid_on: date | None = None) -> dict:
    """The quarter-level "mark filed": forms already filed keep the version they went in from."""
    for form in forms:
        if form not in filed:
            filed = set_form(filed, form, output_id, version, now, paid_on)
    return filed


def unfile_all(filed: dict, forms: list[str]) -> dict:
    return {key: value for key, value in filed.items() if key not in forms}


def credited_output_id(filed: dict, form: str, legacy_output_id: str | None) -> str | None:
    """The version a quarter's income tax return was filed from (what the annual return credits)."""
    if form in filed:
        return filed[form]["output_id"]
    return legacy_output_id if not filed else None


# Returns whose amended version subtracts what was paid on the original (the quarter inputs' "paid on original").
_PAYMENT_AMENDING = frozenset({"2550Q", "2551Q", "1701Q", "1702Q", "1601EQ"})


def amends_payment(forms: Iterable[str]) -> bool:
    """Any of these (filed or amended) forms is one whose amendment subtracts what the original paid."""
    return any(form in _PAYMENT_AMENDING for form in forms)


def derive(filed: dict, expected: list[str]) -> tuple[datetime | None, str | None]:
    """The period counts as filed once every expected form is; it points at the newest version filed."""
    if not expected or any(form not in filed for form in expected):
        return None, None
    entries = [filed[form] for form in expected]
    newest = max(entries, key=lambda e: e["version"])
    return max(datetime.fromisoformat(e["filed_at"]) for e in entries), newest["output_id"]


def form_amended(filed: dict, form: str, version: int, values: dict | None = None,
                 filed_values: dict | None = None) -> bool:
    """A later version of a filed form is an amended return only when its figures differ from what was filed.

    ``filed_values`` is the filed version's form; unknown (None) counts as changed.
    """
    entry = filed.get(form)
    if entry is None or version <= int(entry["version"]):
        return False
    return filed_values is None or values != filed_values


def amended_forms(filed: dict, forms: dict[str, dict], filed_values: dict[str, dict]) -> set[str]:
    """The filed forms whose figures in a new version differ from the version they were filed from."""
    return {form for form, values in forms.items()
            if form in filed and (filed_values.get(form) is None or values != filed_values[form])}
