"""Audit log: who changed what, when, before → after, and why.

Routers snapshot a row before changing it, change it, then call ``record``. The event is added to the
request's session, so it commits (or rolls back) with the change it describes. Only changed fields are
kept. Any router that mutates firm data should call ``record``; see CLAUDE.md.
"""

import enum
import uuid
from collections.abc import Iterable
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.models.accounting import AAAuditEvent

ENTITIES = frozenset({
    "company", "document", "account", "journal_entry", "books_month", "period", "output", "asset", "employee",
    "atc", "upload",
})
REASON_MAX = 500


def json_safe(value: Any) -> Any:
    """A value JSONB can store: Decimal as plain text, dates as ISO, UUIDs as text, enums by value."""
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, enum.Enum):
        return json_safe(value.value)
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [json_safe(v) for v in value]
    return value


def snapshot(obj: Any, fields: Iterable[str]) -> dict:
    """The named attributes of a row, JSON-safe."""
    return {name: json_safe(getattr(obj, name)) for name in fields}


def diff(before: dict, after: dict) -> tuple[dict, dict]:
    """Only the fields whose values differ; a field missing on one side is ``None`` there."""
    old, new = json_safe(before or {}), json_safe(after or {})
    changed = [k for k in dict.fromkeys([*old, *new]) if old.get(k) != new.get(k)]
    return {k: old.get(k) for k in changed}, {k: new.get(k) for k in changed}


def record(db, *, ent: uuid.UUID, company_id: uuid.UUID, user, entity: str, entity_id: Any, action: str,
           before: dict | None = None, after: dict | None = None, reason: str | None = "", label: str = "",
           always: bool = False) -> AAAuditEvent | None:
    """Add an event to the session (never commits). Nothing is written when nothing changed, unless ``always``."""
    if entity not in ENTITIES:
        raise ValueError(f"Unknown audit entity {entity!r}")
    old, new = diff(before or {}, after or {})
    if before is None:  # a create: nothing existed before
        old = {}
    if after is None:   # a delete: nothing is left after
        new = {}
    if not old and not new and not always:
        return None
    event = AAAuditEvent(
        id=uuid.uuid4(), enterprise_id=ent, company_id=company_id, user_id=getattr(user, "id", None),
        user_label=(getattr(user, "email", "") or "")[:255], entity=entity,
        entity_id=str(entity_id if entity_id is not None else "")[:64], label=(label or "")[:200],
        action=action[:30],
        before=old, after=new, reason=(reason or "").strip()[:REASON_MAX],
    )
    db.add(event)
    return event


_PERIOD_FIELDS = frozenset({"period_year", "period_quarter", "period_month", "period_locked"})


def document_action(old: dict, new: dict) -> str:
    """The name of a document edit from its diff: overrides first (reviewed, excluded), then a move, else update."""
    if "reviewed" in new:
        return "mark_reviewed" if new["reviewed"] else "unmark_reviewed"
    if "excluded" in new:
        return "exclude" if new["excluded"] else "include"
    if new and set(new) <= _PERIOD_FIELDS:
        return "move"
    return "update"


def document_label(doc) -> str:
    """``5838 · Luzon Paint``: the number and the other party, as the document panel shows them."""
    party = doc.buyer_name if getattr(doc, "client_role", "buyer") == "seller" else doc.seller_name
    return " · ".join(p for p in ((doc.doc_number or "no number"), (party or "").strip()) if p)


def month_label(day: date) -> str:
    return day.strftime("%B %Y")


def employee_label(data: dict) -> str:
    data = data or {}
    if data.get("last_name"):
        first = (data.get("first_name") or "").strip()
        return f"{data['last_name']}, {first}".strip(", ")
    return (data.get("full_name") or "Employee").strip()
