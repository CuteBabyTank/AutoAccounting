"""Write-mode integration contracts using in-memory objects, never a DB or model provider."""
import inspect
import json
import uuid
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.models.accounting import AATask
from app.models.user import UserRole
from app.schemas.accounting_assistant import ActionOut
from app.schemas.accounting_work import FirmSettingsIn
from app.services.accounting import audit
from app.services.accounting.assistant import action_policy, actions, loop, tools


def test_public_action_contract_has_exact_fields():
    assert set(ActionOut.model_fields) == {
        'id', 'kind', 'summary', 'details', 'destructive', 'status', 'error', 'company_name',
        'created_at', 'expires_at', 'applied_at', 'undo_until', 'undone_at', 'can_confirm', 'can_undo', 'user_name'}


def test_write_tools_match_signatures_and_never_expose_confirmation():
    assert len(tools.WRITE_TOOLS) == 6
    for tool in tools.WRITE_TOOLS:
        params = inspect.signature(tool.run).parameters
        assert set(tool.parameters['properties']) <= set(params)
        for required in tool.parameters['required']:
            assert params[required].default is inspect.Parameter.empty
    assert not any('confirm' in t.name or 'undo' in t.name for t in tools.WRITE_TOOLS)


@pytest.mark.parametrize('kind,changes', [
    ('update_task', {'company_id': str(uuid.uuid4())}),
    ('update_task', {'status': 'filed'}),
    ('update_document', {'gross_amount': '1.00'}),
    ('update_document', {'period_year': 2026}),
    ('update_document', {'period_year': 2026, 'period_quarter': None}),
    ('update_task', {'title': None}),
])
def test_disallowed_and_incomplete_edits_are_rejected(kind, changes):
    with pytest.raises((ValueError, tools.ToolError)):
        actions.validate_body(kind, changes)


def test_write_task_status_translates_to_existing_handler():
    for status, stored in [('todo', 'open'), ('open', 'open'), ('in_progress', 'in_progress'), ('done', 'done')]:
        assert actions.validate_body('update_task', {'status': status})['status'] == stored
    with pytest.raises((ValueError, tools.ToolError)):
        actions.validate_body('update_task', {'status': 'filed'})


def test_full_deleted_task_snapshot_round_trips_identity_and_provenance():
    ident, ent, creator = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    now = datetime(2026, 11, 4, 0, 0, tzinfo=timezone.utc)
    values = dict(id=ident, enterprise_id=ent, company_id=None, document_id=None, period_year=None,
                  period_quarter=None, title='Call supplier', notes='Ask for invoice', due_date=date(2026, 11, 5),
                  assignee_id=creator, assigned_auto=True, status='done', priority='high', created_by=creator,
                  completed_by=creator, completed_at=now, created_at=now, updated_at=now)
    task = AATask(**values)
    saved = json.loads(json.dumps(actions.snapshot(task)))
    assert actions.typed_values(AATask, saved) == values


@pytest.mark.parametrize('role,created_by,kind,allowed', [
    (UserRole.EMPLOYEE, 'self', 'delete_task', True),
    (UserRole.EMPLOYEE, 'other', 'delete_task', False),
    (UserRole.EMPLOYEE, 'self', 'delete_document', False),
    (UserRole.MANAGER, 'other', 'delete_document', True),
    (UserRole.ENTERPRISE, 'other', 'delete_task', True),
])
def test_delete_permission_is_checked_even_when_everyone_can_write(role, created_by, kind, allowed):
    user = SimpleNamespace(id=uuid.uuid4(), role=role)
    row = SimpleNamespace(created_by=user.id if created_by == 'self' else uuid.uuid4())
    if allowed:
        actions.delete_rights(kind, row, user)
    else:
        with pytest.raises(HTTPException) as exc:
            actions.delete_rights(kind, row, user)
        assert exc.value.status_code == 403


def test_settings_accept_only_the_three_write_modes():
    for mode in ('off', 'managers', 'everyone'):
        assert FirmSettingsIn(assistant_writes=mode).assistant_writes == mode
    with pytest.raises(ValueError):
        FirmSettingsIn(assistant_writes='always')


def test_action_table_is_force_rls_and_settings_have_additive_migrations():
    from app.services.accounting.rls import rls_statements
    from app.services.accounting.schema import column_statements
    statements = rls_statements()
    assert 'ALTER TABLE aa_assistant_actions FORCE ROW LEVEL SECURITY' in statements
    assert any('CREATE POLICY aa_assistant_actions_firm' in s and 'WITH CHECK' in s for s in statements)
    assert any("assistant_writes TEXT NOT NULL DEFAULT 'managers'" in s for s in column_statements())
    assert any('aa_documents ADD COLUMN IF NOT EXISTS notes' in s for s in column_statements())


def test_action_endpoints_are_covered_by_write_feature():
    from app.services.features import feature_for_route
    for method, path in [('GET', '/assistant/actions'), ('POST', '/assistant/actions/id/confirm'),
                         ('POST', '/assistant/actions/id/cancel'), ('POST', '/assistant/actions/id/undo')]:
        assert feature_for_route(method, '/api/accounting' + path) == 'assistant_write'


def test_audit_context_resets_on_error_and_nests():
    assert audit.casper_reason.get() == ''
    with audit.casper_context('Ana'):
        with pytest.raises(RuntimeError), audit.casper_context('Bea'):
            assert audit.casper_reason.get() == 'Casper (confirmed by Bea)'
            raise RuntimeError('failed mutation')
        assert audit.casper_reason.get() == 'Casper (confirmed by Ana)'
    assert audit.casper_reason.get() == ''


async def test_sse_proposals_follow_observations_and_fourth_proposal_is_refused(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, 'assistant_turn_seconds', 180)
    monkeypatch.setattr(settings, 'assistant_llm_timeout_seconds', 5)
    monkeypatch.setattr(loop, 'MAX_STEPS', 5)
    monkeypatch.setattr(loop, 'MAX_CALLS_PER_STEP', 3)
    ctx = tools.Ctx(db=None, user=SimpleNamespace(id='person'), ent='firm', write=True)
    replies = [
        {'content': '', 'tool_calls': [{'id': str(n), 'type': 'function', 'function': {
            'name': 'propose_create_task', 'arguments': json.dumps({'title': f'Task {n}'})}}]}
        for n in range(4)] + [{'content': 'Please press Confirm on each proposal card.'}]

    async def generate(contents, declarations, choice):
        assert any(t['function']['name'] == 'propose_create_task' for t in declarations)
        return replies.pop(0)

    async def call(context, name, args):
        try:
            action_policy.check_proposal_limit(context.proposals)
        except ValueError as exc:
            return tools.Result({'error': str(exc)})
        context.proposals += 1
        return tools.Result({'proposal': {'id': str(context.proposals), 'summary': args['title']}})

    monkeypatch.setattr(tools, 'call', call)
    events = [e async for e in loop.run(ctx, 'Make a task for each of these reminders.', [], generate)]
    proposals = [e for e in events if e['type'] == 'proposal']
    assert len(proposals) == 3
    for i, event in enumerate(events):
        if event['type'] == 'proposal':
            assert events[i - 1]['type'] == 'observation' and events[i - 1]['ok']
    assert any(e['type'] == 'observation' and not e['ok'] and 'bulk' in e['summary'] for e in events)
    assert events[-1]['type'] == 'final'


@pytest.mark.parametrize('mode', ['off', 'everyone'])
def test_settings_response_preserves_saved_nondefault_write_mode(mode):
    from app.routers.accounting_work import _settings_out
    row = SimpleNamespace(assistant_writes=mode, auto_assign=True, approve_before_close=False, deadline_days=7)
    user = SimpleNamespace(role=UserRole.ENTERPRISE)
    assert _settings_out(row, user).assistant_writes == mode


async def test_confirm_applies_once_and_sets_seven_day_undo(monkeypatch):
    from contextlib import asynccontextmanager
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    action = SimpleNamespace(id=uuid.uuid4(), status='proposed', expires_at=now + timedelta(minutes=15),
                             enterprise_id=uuid.uuid4(), kind='delete_task', target_id=None, undo_data=None,
                             applied_at=None, undo_until=None, error=None)
    user = SimpleNamespace(id=uuid.uuid4())
    target_id = uuid.uuid4()
    applied = []

    @asynccontextmanager
    async def transaction():
        yield

    @asynccontextmanager
    async def child(db, person):
        assert person is user
        yield db

    async def noop(*args, **kwargs):
        pass

    db = SimpleNamespace(begin_nested=transaction, commit=noop, refresh=noop)

    async def get_action(db, person, ident, *, own=False):
        assert own is True and person is user and ident == action.id
        return action

    async def apply(db, row, person):
        applied.append(row.id)
        return target_id, {'before': {'id': str(target_id), 'title': 'Call'}, 'after': None}

    async def out(db, row, person):
        return row

    monkeypatch.setattr(actions, 'get_action', get_action)
    monkeypatch.setattr(actions, 'check_caps', noop)
    monkeypatch.setattr(actions, 'require_write', noop)
    monkeypatch.setattr(actions, 'route_session', child)
    monkeypatch.setattr(actions, 'apply', apply)
    monkeypatch.setattr(actions, 'action_out', out)
    monkeypatch.setattr(actions, 'person_name', lambda person: 'Ana')
    result = await actions.confirm(db, user, action.id)
    assert result.status == 'applied' and result.target_id == target_id
    assert result.undo_data['before']['title'] == 'Call'
    assert result.undo_until - result.applied_at == timedelta(days=7)
    with pytest.raises(HTTPException) as exc:
        await actions.confirm(db, user, action.id)
    assert exc.value.status_code == 409 and applied == [action.id]


async def test_confirm_preserves_route_failure_status_and_records_failed(monkeypatch):
    from contextlib import asynccontextmanager
    from datetime import timedelta
    action = SimpleNamespace(id=uuid.uuid4(), status='proposed', enterprise_id=uuid.uuid4(), kind='delete_task',
                             expires_at=datetime.now(timezone.utc) + timedelta(minutes=15), error=None)
    commits = []

    @asynccontextmanager
    async def transaction():
        yield

    @asynccontextmanager
    async def child(db, user):
        yield db

    async def noop(*args, **kwargs):
        pass

    async def get_action(*args, **kwargs):
        return action

    async def apply(*args):
        assert audit.casper_reason.get() == 'Casper (confirmed by Ana)'
        raise HTTPException(403, 'Only the task creator or a manager can delete it')

    async def commit():
        commits.append(action.status)

    db = SimpleNamespace(begin_nested=transaction, commit=commit, refresh=noop)
    monkeypatch.setattr(actions, 'get_action', get_action)
    monkeypatch.setattr(actions, 'check_caps', noop)
    monkeypatch.setattr(actions, 'require_write', noop)
    monkeypatch.setattr(actions, 'route_session', child)
    monkeypatch.setattr(actions, 'apply', apply)
    monkeypatch.setattr(actions, 'person_name', lambda person: 'Ana')
    with pytest.raises(HTTPException) as exc:
        await actions.confirm(db, SimpleNamespace(id=uuid.uuid4()), action.id)
    assert exc.value.status_code == 403
    assert action.status == 'failed' and action.error == 'Only the task creator or a manager can delete it'
    assert commits == ['failed'] and audit.casper_reason.get() == ''


async def test_rejected_proposal_releases_lookup_transaction(monkeypatch):
    rolled_back = []

    async def rollback():
        rolled_back.append(True)

    async def reject(*args, **kwargs):
        raise tools.ToolError('Several tasks match')

    monkeypatch.setattr(actions, 'propose', reject)
    ctx = SimpleNamespace(db=SimpleNamespace(rollback=rollback))
    with pytest.raises(tools.ToolError, match='Several tasks'):
        await tools._propose(ctx, 'delete_task', target='Call')
    assert rolled_back == [True]


def test_proposal_values_match_route_normalization():
    assert actions.validate_body('update_task', {'title': '  Call supplier  '})['title'] == 'Call supplier'
    assert actions.validate_body('update_document', {'gl_account_code': ' 6100 '})['gl_account_code'] == '6100'
    assert actions.validate_body('update_document', {'gl_account_code': None})['gl_account_code'] == ''
    with pytest.raises((ValueError, tools.ToolError)):
        actions.validate_body('update_task', {'title': '   '})


async def test_fourth_proposal_fails_before_any_database_access():
    ctx = tools.Ctx(db=None, user=None, ent=uuid.uuid4(), write=True, proposals=3)
    with pytest.raises(ValueError, match='bulk'):
        await actions.propose(ctx, 'create_task', changes={'title': 'Fourth task'})


async def test_a_filing_proposal_can_never_mark_filed(monkeypatch):
    ctx = tools.Ctx(db=None, user=SimpleNamespace(id=uuid.uuid4()), ent=uuid.uuid4(), write=True)
    async def allowed(*args):
        pass
    async def company(*args):
        return SimpleNamespace(id=uuid.uuid4())
    monkeypatch.setattr(actions, 'require_write', allowed)
    monkeypatch.setattr(actions, 'check_caps', allowed)
    monkeypatch.setattr(actions, 'resolve_company', company)
    with pytest.raises(tools.ToolError, match='never filed'):
        await actions.propose(ctx, 'assign_filing', company='Client', year=2026, quarter=4,
                              form='2550Q', changes={'status': 'filed'})


async def test_foreign_action_is_indistinguishable_from_missing_action(monkeypatch):
    from sqlalchemy.dialects import postgresql
    user = SimpleNamespace(id=uuid.uuid4(), role=UserRole.EMPLOYEE, enterprise_id=uuid.uuid4())
    statements = []
    class DB:
        async def execute(self, query):
            statements.append(query)
            return SimpleNamespace(scalar_one_or_none=lambda: None)
    async def lock(*args):
        pass
    monkeypatch.setattr(actions, 'lock_firm', lock)
    with pytest.raises(HTTPException) as exc:
        await actions.get_action(DB(), user, uuid.uuid4(), own=True)
    assert exc.value.status_code == 404 and exc.value.detail == 'Proposal not found'
    compiled = statements[0].compile(dialect=postgresql.dialect())
    assert user.enterprise_id in compiled.params.values() and user.id in compiled.params.values()
    assert 'FOR UPDATE' in str(compiled)


async def test_deleted_task_snapshot_is_stored_before_calling_delete_handler(monkeypatch):
    from app.routers import accounting_tasks
    ident, ent, user_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    task = AATask(id=ident, enterprise_id=ent, company_id=None, title='Call supplier', notes='Original note',
                  created_by=user_id)
    before = actions.snapshot(task)
    action = SimpleNamespace(id=uuid.uuid4(), kind='delete_task', enterprise_id=ent, company_id=None,
                             target_id=ident, undo_data=None,
                             args={'body': {}, 'expected': action_policy.fingerprint(before)})
    writes = []
    class DB:
        async def execute(self, statement):
            writes.append(statement)
        async def flush(self):
            pass
    async def target(*args):
        return task
    async def delete(task_id, *, user, db):
        assert task_id == ident and action.undo_data['before'] == before
        assert writes, 'Undo snapshot must reach the transaction before deletion'
    monkeypatch.setattr(actions, 'target_row', target)
    monkeypatch.setattr(accounting_tasks, 'delete_task', delete)
    target_id, undo = await actions.apply(DB(), action, SimpleNamespace(id=user_id, role=UserRole.EMPLOYEE))
    assert target_id == ident and undo['before'] == before and undo['after'] is None


async def test_route_session_preserves_outer_transaction_and_rls_identity(monkeypatch):
    from contextlib import contextmanager
    from app.services.accounting.assistant import scope
    connection = object()
    options, identities = {}, []
    class Parent:
        async def flush(self):
            pass
        async def connection(self):
            return connection
        async def commit(self):
            pytest.fail('A route session must never commit the outer session')
    class Child:
        def __init__(self, **kwargs):
            options.update(kwargs)
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def commit(self):
            pass
    async def bind(db, identity):
        identities.append(identity)
    @contextmanager
    def firm_reads(db, ent):
        yield
    user = SimpleNamespace(id=uuid.uuid4(), role=UserRole.ENTERPRISE)
    monkeypatch.setattr(actions, 'AsyncSession', Child)
    monkeypatch.setattr(actions, 'bind_session_user', bind)
    monkeypatch.setattr(scope, 'firm_reads', firm_reads)
    async with actions.route_session(Parent(), user) as child:
        await child.commit()  # existing handlers may commit and then keep reading
    assert options == {'bind': connection, 'expire_on_commit': False, 'join_transaction_mode': 'create_savepoint'}
    assert identities == [str(user.id)]
