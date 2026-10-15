"""Immutable version snapshots and the differences between two versions (pure)."""

from dataclasses import asdict
from decimal import Decimal

from app.services.accounting.compute.engine import QuarterResult
from app.services.accounting.compute.inputs import CompanyFacts


def _text(value) -> str:
    if isinstance(value, Decimal):
        return format(value, "f")
    return "" if value is None else str(value)


def snapshot(result: QuarterResult, company: CompanyFacts) -> dict:
    return {
        "company": asdict(company),
        "forms": {form: {key: _text(v) for key, v in items.items()} for form, items in result.forms.items()},
        "ledgers": {name: [{col: _text(v) for col, v in row.items()} for row in rows]
                    for name, rows in result.ledgers.items()},
    }


def diff_snapshots(old: dict | None, new: dict) -> dict:
    """Every form value and ledger cell that is new or different in ``new``."""
    old = old or {}
    forms: dict[str, dict] = {}
    for form, items in new["forms"].items():
        before = old.get("forms", {}).get(form, {})
        changed = {key: [before.get(key), value] for key, value in items.items()
                   if not key.startswith("_") and before.get(key) != value}
        if changed:
            forms[form] = changed
    ledgers: dict[str, dict] = {}
    for name, rows in new["ledgers"].items():
        before_rows = {row["key"]: row for row in old.get("ledgers", {}).get(name, [])}
        added: list[str] = []
        changed_rows: dict[str, dict] = {}
        for row in rows:
            previous = before_rows.get(row["key"])
            if previous is None:
                added.append(row["key"])
                continue
            columns = {col: [previous.get(col), value] for col, value in row.items()
                       if col != "key" and col in previous and previous.get(col) != value}
            if columns:
                changed_rows[row["key"]] = columns
        current = {row["key"] for row in rows}
        removed = [key for key in before_rows if key not in current]
        if added or changed_rows or removed:
            ledgers[name] = {"added": added, "changed": changed_rows, "removed": removed}
    return {"forms": forms, "ledgers": ledgers}


def count_changes(diff: dict | None) -> int:
    if not diff:
        return 0
    n = sum(len(items) for items in diff["forms"].values())
    for change in diff["ledgers"].values():
        n += len(change["added"]) + len(change["changed"]) + len(change["removed"])
    return n
