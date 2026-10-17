"""Tasks: overdue and ordering (pure)."""

from datetime import date
from types import SimpleNamespace

from app.services.accounting.compute.tasks import is_task_overdue, sort_tasks


def test_task_overdue():
    today = date(2026, 10, 17)
    assert is_task_overdue("open", date(2026, 10, 16), today)
    assert not is_task_overdue("open", today, today)
    assert not is_task_overdue("done", date(2026, 10, 1), today)
    assert not is_task_overdue("in_progress", None, today)


def test_sort_tasks_open_first_then_due_then_priority():
    def t(name, status="open", due=None, priority="normal"):
        return SimpleNamespace(title=name, status=status, due_date=due, priority=priority, created_at=0)

    rows = [t("done", "done", date(2026, 1, 1)), t("no date"), t("late", due=date(2026, 10, 1)),
            t("soon low", due=date(2026, 10, 20), priority="low"), t("soon high", due=date(2026, 10, 20), priority="high")]
    assert [r.title for r in sort_tasks(rows)] == ["late", "soon high", "soon low", "no date", "done"]


def test_edit_does_not_recheck_unchanged_links(monkeypatch):
    """Completing a task whose document was deleted or whose assignee left the firm must not fail."""
    import asyncio
    import uuid

    import pytest
    from fastapi import HTTPException

    from app.routers import accounting_tasks as tasks

    calls = []

    async def gone(*args, **kwargs):
        calls.append(args[-1])
        raise HTTPException(404, "gone")

    class NoDb:
        async def execute(self, *args, **kwargs):
            raise HTTPException(404, "Document not found")

    monkeypatch.setattr(tasks, "company_or_404", gone)
    monkeypatch.setattr(tasks, "assignee_or_400", gone)
    values = {"company_id": uuid.uuid4(), "document_id": uuid.uuid4(), "assignee_id": uuid.uuid4(),
              "period_year": None, "period_quarter": None}
    asyncio.run(tasks._check_links(NoDb(), uuid.uuid4(), dict(values), set()))   # only status changed
    assert calls == []
    with pytest.raises(HTTPException):
        asyncio.run(tasks._check_links(NoDb(), uuid.uuid4(), dict(values), {"assignee_id"}))
    with pytest.raises(HTTPException):
        asyncio.run(tasks._check_links(NoDb(), uuid.uuid4(), dict(values)))   # a new task checks everything
