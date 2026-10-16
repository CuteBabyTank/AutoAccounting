"""Audit log responses."""

import uuid
from datetime import datetime

from pydantic import BaseModel


class AuditEventOut(BaseModel):
    id: uuid.UUID
    at: datetime
    company_id: uuid.UUID
    user_id: uuid.UUID | None
    user_name: str
    entity: str
    entity_id: str
    label: str
    action: str
    before: dict
    after: dict
    reason: str


class AuditUserOut(BaseModel):
    id: uuid.UUID
    name: str


class AuditPageOut(BaseModel):
    events: list[AuditEventOut]
    total: int
    users: list[AuditUserOut]   # people with events in this scope (for the filter)
