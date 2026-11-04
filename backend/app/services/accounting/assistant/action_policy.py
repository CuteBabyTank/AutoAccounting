"""Deterministic write policy. No database, model provider, or application configuration."""
import hashlib
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException

PROPOSAL_TTL = timedelta(minutes=15)
UNDO_TTL = timedelta(days=7)
DELETE_KINDS = frozenset({"delete_task", "delete_document"})
MANAGERS = frozenset({"admin", "enterprise", "manager"})


def day_bounds(now: datetime) -> tuple[datetime, datetime]:
    local = now.astimezone(ZoneInfo("Asia/Manila"))
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(timezone.utc), (start + timedelta(days=1)).astimezone(timezone.utc)


def cap_problem(kind: str, changes: int, personal_deletes: int, firm_deletes: int) -> str:
    if changes >= 40:
        return "Casper's daily limit of 40 changes per person has been reached. Use the screen for more changes."
    if kind in DELETE_KINDS:
        if personal_deletes >= 10:
            return "Casper's daily limit of 10 deletes per person has been reached. Use the screen."
        if firm_deletes >= 30:
            return "Casper's daily limit of 30 deletes per firm has been reached. Use the screen."
    return ""


def check_confirm(status: str, expires_at: datetime, now: datetime) -> None:
    if status != "proposed":
        raise HTTPException(409, "This proposal is no longer awaiting confirmation")
    if now >= expires_at:
        raise HTTPException(409, "This proposal has expired. Ask Casper for a new proposal.")


def check_cancel(status: str) -> None:
    if status != "proposed":
        raise HTTPException(409, "This proposal is no longer awaiting confirmation")


def check_undo(status: str, undo_until: datetime | None, now: datetime) -> None:
    if status != "applied":
        raise HTTPException(409, "Only an applied change can be undone")
    if undo_until is None or now >= undo_until:
        raise HTTPException(410, "The 7-day restore period has ended")


def check_unchanged(current: dict, after: dict) -> None:
    if any(k not in current or current[k] != value for k, value in after.items()):
        raise HTTPException(409, "This record has changed since Casper's change. Use the screen to edit it.")


def check_proposal_limit(count: int) -> None:
    if count >= 3:
        raise ValueError("At most 3 proposals per turn. Stop and ask the person to do bulk work on the screen.")


def write_permission(setting: str, role: str, platform_on: bool, level: str | None = None) -> dict:
    """May this person turn on write mode? ``level`` = their own Casper level from the Team page (None = the
    firm default). The platform switch and the firm's "off" win over everything; the owner is never limited."""
    reason = ""
    personal = level if role in ("employee", "manager") else None
    if not platform_on:
        reason = "Casper's changes are switched off for maintenance"
    elif setting == "off":
        reason = "Your firm has Casper's changes turned off"
    elif personal in ("off", "read"):
        reason = "Your firm owner has set Casper to answer questions only for you"
    elif personal == "write":
        reason = ""
    elif role not in MANAGERS and (setting != "everyone" or role != "employee"):
        reason = "Casper's changes are for managers and the firm owner at your firm"
    return {"allowed": not bool(reason), "reason": reason}


def fingerprint(values: dict) -> str:
    """Pin proposal facts without retaining a second full deleted-task restore snapshot in args."""
    payload = json.dumps(values, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
