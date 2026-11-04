"""Public Casper proposal card contract."""
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class ActionDetail(BaseModel):
    label: str
    value: str


class ActionOut(BaseModel):
    id: uuid.UUID
    kind: str
    summary: str
    details: list[ActionDetail]
    destructive: bool
    status: Literal["proposed", "applied", "failed", "cancelled", "expired", "undone"]
    error: str | None
    company_name: str
    created_at: datetime
    expires_at: datetime
    applied_at: datetime | None
    undo_until: datetime | None
    undone_at: datetime | None
    can_confirm: bool
    can_undo: bool
    user_name: str
