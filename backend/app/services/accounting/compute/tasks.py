"""Tasks: overdue and the list order (pure)."""

import uuid
from datetime import date, datetime

_PRIORITY = {"high": 0, "normal": 1, "low": 2}


def is_task_overdue(status: str, due: date | None, today: date) -> bool:
    return status != "done" and due is not None and due < today


def sort_tasks(rows: list) -> list:
    """Open before done; earliest due first (no due date last); high priority first; oldest first."""
    return sorted(rows, key=lambda r: (r.status == "done", r.due_date is None, r.due_date or date.max,
                                       _PRIORITY.get(r.priority, 1), r.created_at))


def completion_fields(old_status: str | None, status: str, actor: uuid.UUID, now: datetime,
                      completed_at: datetime | None, completed_by: uuid.UUID | None) -> tuple[datetime | None, uuid.UUID | None]:
    """Completion belongs to the person changing the status, preserved on later unrelated edits."""
    if status != "done":
        return None, None
    if old_status != "done":
        return now, actor
    return completed_at, completed_by
