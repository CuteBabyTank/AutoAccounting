"""Casper write policy and contract tests, without a database or model service."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import uuid

import pytest
from fastapi import HTTPException

from app.services.accounting.assistant import action_policy as policy

NOW = datetime(2026, 11, 4, 16, 0, tzinfo=timezone.utc)


def test_manila_day_boundaries():
    assert policy.day_bounds(NOW) == (
        datetime(2026, 11, 4, 16, tzinfo=timezone.utc), datetime(2026, 11, 5, 16, tzinfo=timezone.utc))
    assert policy.day_bounds(NOW - timedelta(microseconds=1))[0] == datetime(2026, 11, 3, 16, tzinfo=timezone.utc)


@pytest.mark.parametrize('kind,changes,personal,firm,blocked', [
    ('create_task', 39, 10, 30, False), ('create_task', 40, 0, 0, True),
    ('delete_task', 0, 9, 29, False), ('delete_task', 0, 10, 0, True),
    ('delete_document', 0, 0, 30, True), ('delete_document', 40, 0, 0, True),
])
def test_caps(kind, changes, personal, firm, blocked):
    assert bool(policy.cap_problem(kind, changes, personal, firm)) == blocked


@pytest.mark.parametrize('status', ['applied', 'failed', 'cancelled', 'expired', 'undone'])
def test_confirm_is_single_use(status):
    with pytest.raises(HTTPException) as exc:
        policy.check_confirm(status, NOW + timedelta(minutes=1), NOW)
    assert exc.value.status_code == 409


def test_confirm_expiry_boundary():
    policy.check_confirm('proposed', NOW + timedelta(microseconds=1), NOW)
    with pytest.raises(HTTPException) as exc:
        policy.check_confirm('proposed', NOW, NOW)
    assert exc.value.status_code == 409


def test_undo_window_and_status():
    policy.check_undo('applied', NOW + timedelta(microseconds=1), NOW)
    for status, until, code in [('applied', NOW, 410), ('undone', NOW + timedelta(days=1), 409),
                                ('proposed', None, 409)]:
        with pytest.raises(HTTPException) as exc:
            policy.check_undo(status, until, NOW)
        assert exc.value.status_code == code


def test_changed_since_rejects_missing_and_modified_fields():
    policy.check_unchanged({'title': 'Call', 'notes': ''}, {'title': 'Call', 'notes': ''})
    for current in ({'title': 'Edited', 'notes': ''}, {'title': 'Call'}):
        with pytest.raises(HTTPException) as exc:
            policy.check_unchanged(current, {'title': 'Call', 'notes': ''})
        assert exc.value.status_code == 409 and 'changed since' in exc.value.detail


def test_three_proposals_per_turn():
    for count in range(3):
        policy.check_proposal_limit(count)
    with pytest.raises(ValueError, match='bulk'):
        policy.check_proposal_limit(3)


def test_write_tools_absent_unless_enabled():
    from app.services.accounting.assistant import loop
    assert not any(t['function']['name'].startswith('propose_') for t in loop.declarations())
    assert {t['function']['name'] for t in loop.declarations(write=True)} - {
        t['function']['name'] for t in loop.declarations()} == {
            'propose_create_task', 'propose_update_task', 'propose_delete_task',
            'propose_update_document', 'propose_delete_document', 'propose_assign_filing'}


def test_read_only_prompt_unchanged():
    from app.services.accounting.assistant.prompt import SYSTEM, system_instruction
    from app.services.accounting.assistant.prompt import calendar
    assert system_instruction(NOW.date()) == SYSTEM.format(today='2026-11-04, ' + calendar(NOW.date()))
    assert 'press Confirm' in system_instruction(NOW.date(), write=True)


async def test_write_tool_cannot_be_called_when_off():
    from app.services.accounting.assistant import tools
    user = SimpleNamespace(id=uuid.uuid4())
    ctx = tools.Ctx(db=None, user=user, ent=user.id)
    result = await tools.call(ctx, 'propose_delete_task', {'task': str(uuid.uuid4())})
    assert 'error' in result.data
    assert 'write mode' in result.data['error'].lower()


def test_casper_audit_reason_is_scoped_and_explicit_reason_wins():
    from app.services.accounting import audit
    db = SimpleNamespace(add=lambda row: None)
    args = dict(ent=uuid.uuid4(), company_id=None, user=SimpleNamespace(id=uuid.uuid4(), email='a@a.com'),
                entity='task', entity_id=uuid.uuid4(), action='update', before={'title': 'a'}, after={'title': 'b'})
    with audit.casper_context('Ana'):
        assert audit.record(db, **args).reason == 'Casper (confirmed by Ana)'
        assert audit.record(db, **args, reason='Manual reason').reason == 'Manual reason'
    assert audit.record(db, **args).reason == ''


@pytest.mark.parametrize('setting,role,on,allowed', [
    ('off', 'enterprise', True, False), ('managers', 'manager', True, True),
    ('managers', 'employee', True, False), ('everyone', 'employee', True, True),
    ('everyone', 'enterprise', False, False),
])
def test_write_permission(setting, role, on, allowed):
    assert policy.write_permission(setting, role, on)['allowed'] == allowed


def test_snapshot_fingerprint_ignores_key_order_but_detects_field_changes():
    first = {"title": "Call", "notes": "", "nested": {"a": 1, "b": 2}}
    assert policy.fingerprint(first) == policy.fingerprint({
        "nested": {"b": 2, "a": 1}, "notes": "", "title": "Call"})
    assert policy.fingerprint(first) != policy.fingerprint(first | {"title": "Changed"})
    assert len(policy.fingerprint(first)) == 64


@pytest.mark.parametrize('status', ['applied', 'failed', 'cancelled', 'expired', 'undone'])
def test_cancel_cannot_reopen_a_terminal_proposal(status):
    with pytest.raises(HTTPException) as exc:
        policy.check_cancel(status)
    assert exc.value.status_code == 409


def test_cancel_can_only_transition_a_proposal():
    policy.check_cancel('proposed')
