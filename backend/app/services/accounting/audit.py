"""Append audit events to the caller's transaction; routers own the commit."""
import json
import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel
from sqlalchemy import inspect

from app.models.accounting import AAAuditEvent


def _json_default(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, (Decimal, uuid.UUID)):
        return str(value)
    if isinstance(value, BaseModel):
        return value.model_dump(mode="python")
    raise TypeError(f"Cannot audit {type(value).__name__}")


def json_copy(value):
    return json.loads(json.dumps(value, default=_json_default))


def snapshot(row) -> dict:
    """Read mapped columns now, before mutation (including detached copies of JSON)."""
    return json_copy({a.key: getattr(row, a.key) for a in inspect(type(row)).column_attrs})


def record_event(db, *, enterprise_id, company_id, user, entity: str, entity_id,
                 action: str, before=None, after=None, reason: str = "") -> AAAuditEvent:
    event = AAAuditEvent(
        enterprise_id=enterprise_id, company_id=company_id, user_id=user.id,
        user_name=getattr(user, "nickname", None) or getattr(user, "name", None) or getattr(user, "email", "") or str(user.id),
        entity=entity, entity_id=str(entity_id), action=action,
        before=json_copy(before or {}), after=json_copy(after or {}), reason=reason.strip(),
    )
    db.add(event)
    return event
