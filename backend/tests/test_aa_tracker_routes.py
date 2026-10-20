"""Tracker route isolation and mutations with in-memory rows/SQL capture, no database."""
import asyncio
import uuid
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from app.models.accounting import AAAuditEvent, AATask
from app.models.user import User, UserRole
from app.routers import accounting_tasks as tasks
from app.routers import accounting_work as work
from app.schemas.accounting_work import HandlerIn, TaskIn, TaskPatch


def sql(stmt):
    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


class Result:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def scalar_one_or_none(self):
        return self.rows[0] if self.rows else None

    def scalars(self):
        return self

    def all(self):
        return self.rows

    def first(self):
        return self.rows[0] if self.rows else None

    def __iter__(self):
        return iter(self.rows)


class Db:
    def __init__(self, task=None):
        self.task, self.statements, self.added = task, [], []

    async def execute(self, stmt):
        self.statements.append(sql(stmt))
        return Result([self.task] if self.task and "FROM aa_tasks" in sql(stmt) else [])

    def add(self, row):
        self.added.append(row)

    async def commit(self):
        pass


def manager():
    return User(id=uuid.uuid4(), enterprise_id=uuid.uuid4(), email="manager@firm.test", role=UserRole.MANAGER)


def test_tracker_queries_always_filter_firm_and_window():
    from app.services.accounting.assignment import open_tasks_query
    from app.services.accounting.work_history import completed_tasks_query, filed_periods_query
    ent = uuid.uuid4()
    start, end = date(2026, 10, 1), date(2026, 10, 31)
    for stmt, table in ((open_tasks_query(ent, start, end), "aa_tasks"),
                        (completed_tasks_query(ent, start, end), "aa_tasks"),
                        (filed_periods_query(ent, start, end), "aa_periods")):
        statement = sql(stmt)
        assert f"{table}.enterprise_id = '{ent}'" in statement
        assert "2026-10-01" in statement and ("2026-10-31" in statement or "2026-11-01" in statement)
    assert "jsonb_each" in sql(filed_periods_query(ent, start, end))  # partially filed periods included
    assert "due_date IS NULL" in sql(open_tasks_query(ent, start, end))


def test_history_uses_scope_and_forces_employee_actor(monkeypatch):
    from app.services.accounting import work_history
    employee = User(id=uuid.uuid4(), enterprise_id=uuid.uuid4(), email="ana@firm.test", role=UserRole.EMPLOYEE)
    captured = []

    async def load(db, ent, *args, **kwargs):
        captured.append((ent, kwargs["person"]))
        return {"items": [], "summary": [], "total": 0, "offset": 0, "limit": 50}

    monkeypatch.setattr(work_history, "load_history", load)
    asyncio.run(work.work_history(start=date(2026, 10, 1), end=date(2026, 10, 31), person=uuid.uuid4(),
                                  company=None, kind=None, limit=50, offset=0, user=employee, db=Db()))
    assert captured == [(employee.enterprise_id, employee.id)]


def test_foreign_company_and_task_ids_are_not_found():
    user, db = manager(), Db()
    cid, tid = uuid.uuid4(), uuid.uuid4()
    with pytest.raises(HTTPException) as handler_error:
        asyncio.run(work.set_company_handler(cid, HandlerIn(handler_id=None), user, db))
    assert handler_error.value.status_code == 404
    assert any(f"aa_companies.enterprise_id = '{user.enterprise_id}'" in s and str(cid) in s for s in db.statements)
    with pytest.raises(HTTPException) as task_error:
        asyncio.run(tasks.update_task(tid, TaskPatch(status="done"), user, db))
    assert task_error.value.status_code == 404
    assert any(f"aa_tasks.enterprise_id = '{user.enterprise_id}'" in s and str(tid) in s for s in db.statements)
    assert db.added == []


def test_autoassign_checks_foreign_company_before_loading_items(monkeypatch):
    user, db = manager(), Db()
    calls = []

    async def forbidden(*args):
        calls.append(args)
        raise AssertionError("Assignment must not run for a foreign company")

    monkeypatch.setattr(work, "assign_open_items", forbidden)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(work.auto_assign_work(None, None, uuid.uuid4(), user, db))
    assert exc.value.status_code == 404 and calls == []
    assert any(f"aa_companies.enterprise_id = '{user.enterprise_id}'" in s for s in db.statements)


def test_employee_cannot_change_handler_or_bulk_assign():
    employee = User(id=uuid.uuid4(), enterprise_id=uuid.uuid4(), email="ana@firm.test", role=UserRole.EMPLOYEE)
    for call in (work.set_company_handler(uuid.uuid4(), HandlerIn(handler_id=None), employee, Db()),
                 work.auto_assign_work(None, None, None, employee, Db())):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(call)
        assert exc.value.status_code == 403


def test_handler_rejects_non_member_like_other_assignees(monkeypatch):
    async def nobody(*args):
        return []
    monkeypatch.setattr(work, "firm_people", nobody)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(work.assignee_or_400(Db(), uuid.uuid4(), uuid.uuid4()))
    assert exc.value.status_code == 400


def test_task_done_create_reopen_and_manual_assignment_audited(monkeypatch):
    user, db = manager(), Db()

    async def out(db, ent, rows):
        return rows

    async def off(*args):
        return SimpleNamespace(auto_assign=False)

    monkeypatch.setattr(tasks, "tasks_out", out)
    monkeypatch.setattr(tasks, "firm_settings", off)
    created = asyncio.run(tasks.create_task(TaskIn(title="Finish client work", status="done"), user, db))
    assert created.completed_by == user.id and created.completed_at is not None
    event = next(e for e in db.added if isinstance(e, AAAuditEvent))
    assert event.after["completed_by"] == str(user.id) and event.after["status"] == "done"
    db.task = created
    asyncio.run(tasks.update_task(created.id, TaskPatch(status="open"), user, db))
    assert created.completed_by is None and created.completed_at is None
    created.assignee_id, created.assigned_auto = user.id, True
    asyncio.run(tasks.update_task(created.id, TaskPatch(notes="Follow up"), user, db))
    assert created.assigned_auto is True
    asyncio.run(tasks.update_task(created.id, TaskPatch(assignee_id=None), user, db))
    assert created.assigned_auto is False and created.assignee_id is None
    assert db.added[-1].action == "assign" and db.added[-1].after["assignee_id"] is None


def test_backfill_uses_status_actor_and_is_idempotent():
    from app.services.accounting.books.task_completed_by import backfill_firm
    ent, actor = uuid.uuid4(), uuid.uuid4()
    task = AATask(id=uuid.uuid4(), enterprise_id=ent, title="Old done task", status="done", completed_by=None)

    class BackfillDb(Db):
        async def execute(self, stmt):
            statement = sql(stmt)
            self.statements.append(statement)
            if "FROM aa_tasks" in statement:
                return Result([task] if task.completed_by is None else [])
            if "FROM aa_audit_events" in statement:
                return Result([SimpleNamespace(entity_id=str(task.id), after={"status": "done"}, user_id=actor)])
            return Result()

    db = BackfillDb()
    assert asyncio.run(backfill_firm(db, ent)) == [task]
    assert task.completed_by == actor and len(db.added) == 1
    assert asyncio.run(backfill_firm(db, ent)) == [] and len(db.added) == 1
    assert all(f"enterprise_id = '{ent}'" in s for s in db.statements if "FROM aa_" in s)


def test_new_columns_are_additive_and_routes_feature_gated():
    from app.services.accounting.schema import column_statements
    from app.services.features import feature_for_route
    statements = "\n".join(column_statements())
    for table, column in (("aa_companies", "handler_id"), ("aa_tasks", "completed_by"),
                          ("aa_tasks", "assigned_auto"), ("aa_work_items", "assigned_auto"),
                          ("aa_firm_settings", "auto_assign")):
        assert f"{table} ADD COLUMN IF NOT EXISTS {column}" in statements
    for method, path in (("POST", "/work/auto-assign"), ("GET", "/work/history"),
                         ("PUT", "/work/companies/a/handler")):
        assert feature_for_route(method, "/api/accounting" + path) == "work"


def test_member_selection_locks_active_rows_against_removal():
    from app.services.accounting.work import firm_people
    db, ent = Db(), uuid.uuid4()
    assert asyncio.run(firm_people(db, ent, lock=True)) == []
    statement = db.statements[0]
    assert "FOR UPDATE" in statement and "users.is_active IS true" in statement
    assert f"users.id = '{ent}'" in statement and f"users.enterprise_id = '{ent}'" in statement
    assert "'manager', 'employee'" in statement


def test_task_create_auto_assigns_only_without_a_manual_assignee(monkeypatch):
    user, selected = manager(), uuid.uuid4()
    calls = []

    async def out(db, ent, rows):
        return rows

    async def on(*args):
        return SimpleNamespace(auto_assign=True)

    async def choose(db, ent, *args):
        calls.append(ent)
        return selected

    async def check(*args):
        pass

    monkeypatch.setattr(tasks, "tasks_out", out)
    monkeypatch.setattr(tasks, "firm_settings", on)
    monkeypatch.setattr(tasks, "choose_for_task", choose)
    monkeypatch.setattr(tasks, "_check_links", check)
    db = Db()
    auto = asyncio.run(tasks.create_task(TaskIn(title="Automatic"), user, db))
    assert auto.assignee_id == selected and auto.assigned_auto
    events = [e for e in db.added if isinstance(e, AAAuditEvent)]
    assert [e.action for e in events] == ["create", "assign"]
    assert events[0].after.get("assignee_id") is None
    assert events[1].reason == "auto-assign" and events[1].after["assignee_id"] == str(selected)
    manual = asyncio.run(tasks.create_task(TaskIn(title="Manual", assignee_id=user.id), user, Db()))
    assert manual.assignee_id == user.id and manual.assigned_auto is False and calls == [user.enterprise_id]


def test_bulk_autoassign_repeat_does_not_write_another_assignment(monkeypatch):
    from app.services.accounting import assignment
    from app.services.accounting.compute.assign import Member
    user, db = manager(), Db()
    pid = uuid.uuid4()
    person = User(id=pid, enterprise_id=user.enterprise_id, role=UserRole.EMPLOYEE,
                  email="ana@firm.test", nickname="Ana", is_active=True)
    task = AATask(id=uuid.uuid4(), enterprise_id=user.enterprise_id, title="Do it", status="open", assignee_id=None, assigned_auto=False)

    async def facts(*args):
        item = {"key": f"task:{task.id}", "company_id": None, "status": task.status,
                "assignee_id": str(task.assignee_id) if task.assignee_id else None}
        return [], [person], [task], [], [item], [Member(str(pid), "Ana", str(user.enterprise_id), "employee")], {}, {}, {}

    monkeypatch.setattr(assignment, "assignment_facts", facts)
    args = (db, user.enterprise_id, user, date(2026, 10, 1), date(2026, 10, 31), date(2026, 10, 21))
    result = asyncio.run(assignment.assign_open_items(*args))
    assert result["total"] == 1 and result["people"] == [{"id": pid, "name": "Ana", "count": 1}]
    assert task.assigned_auto and task.assignee_id == pid
    assert asyncio.run(assignment.assign_open_items(*args)) == {"total": 0, "people": []}
    assert len(db.added) == 1 and db.added[0].reason == "auto-assign"


def test_history_foreign_person_is_not_found_without_user_lookup(monkeypatch):
    from app.services.accounting import work_history

    async def empty(*args, **kwargs):
        return []

    monkeypatch.setattr(work_history, "firm_people", empty)
    monkeypatch.setattr(work_history, "load_cards", empty)
    db, ent = Db(), uuid.uuid4()
    with pytest.raises(HTTPException) as exc:
        asyncio.run(work_history.load_history(db, ent, date(2026, 10, 1), date(2026, 10, 31), date(2026, 10, 21),
                                              person=uuid.uuid4()))
    assert exc.value.status_code == 404
    assert all("FROM users" not in s for s in db.statements)
    assert all(f"enterprise_id = '{ent}'" in s for s in db.statements)


def test_auto_assignment_audits_actual_previous_flag_after_user_deletion():
    from app.services.accounting.assignment import assign_auto
    user, db, new_assignee = manager(), Db(), uuid.uuid4()
    # ON DELETE SET NULL can clear the assignee while the old automatic flag remains.
    task = AATask(id=uuid.uuid4(), enterprise_id=user.enterprise_id, title="Unclaimed", assignee_id=None,
                  assigned_auto=True)
    assign_auto(db, user.enterprise_id, user, task, new_assignee)
    event = db.added[0]
    assert event.before == {"assignee_id": None} and event.after == {"assignee_id": str(new_assignee)}
    assert task.assigned_auto is True and event.reason == "auto-assign"
