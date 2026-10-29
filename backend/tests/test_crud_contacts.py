import asyncio
import uuid
from datetime import date, datetime, timezone
from types import SimpleNamespace
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from fastapi import HTTPException

from app.schemas.accounting_contacts import ContactCreate
from app.services.accounting.contacts import merge_check, plan_contacts, resolve, SeenParty
from app.routers.accounting_contacts import contact_rows
from app.routers import accounting_contacts as router
from app.models.accounting import AAContact
from app.models.user import User, UserRole
from app.schemas.accounting_contacts import MergeIn
from app.services.accounting.books.subledger import Subledger


def test_manual_contact_normalizes_identity_and_rejects_empty_name():
    c = ContactCreate(registered_name='  E2E Customer ', tin='123-456-789', role='customer')
    assert c.registered_name == 'E2E Customer' and c.tin == '123456789'
    with pytest.raises(ValidationError):
        ContactCreate(registered_name='  ', role='customer')
    with pytest.raises(ValidationError):
        ContactCreate(registered_name='E2E Customer', tin='1234', role='customer')


def test_archived_contact_remains_in_accounting_identity_map_and_is_not_recreated():
    row = SimpleNamespace(id=uuid.uuid4(), key='123456789', tin='123456789', registered_name='E2E Customer',
                          role='customer', aliases=[], manual=['registered_name'], address='', vat_status='',
                          merged_into_id=None, archived_at=datetime.now(timezone.utc), payment_terms_days=None)
    seen = SeenParty(row.key, row.tin, row.registered_name, '', 'customer', None, date(2026, 10, 1))
    creates, changes = plan_contacts([seen], [row])
    assert creates == [] and changes == {}  # archive does not detach or silently recreate the identity
    sub = Subledger(date(2026, 10, 1), [row], [], [], [], [], {}, [], {})
    out = contact_rows(sub, 'customer')[0]
    assert out.archived_at == row.archived_at and out.open_balance == Decimal('0')


def contacts():
    ent, company_id = uuid.uuid4(), uuid.uuid4()
    return [AAContact(id=uuid.uuid4(), enterprise_id=ent, company_id=company_id, key=key, tin='',
                      registered_name=name, role='customer', aliases=[], merged_into_id=None, archived_at=None)
            for key, name in [('NAME:e2e_source', 'E2E Source'), ('NAME:e2e_target', 'E2E Target')]]


@pytest.mark.parametrize('archived_index', [0, 1])
def test_merge_check_requires_restoring_archived_source_or_target(archived_index):
    source, target = rows = contacts()
    rows[archived_index].archived_at = datetime.now(timezone.utc)
    assert 'Restore' in merge_check(source, target, rows)
    rows[archived_index].archived_at = None
    assert merge_check(source, target, rows) is None


def contact_db(monkeypatch, rows):
    db = SimpleNamespace(commit=AsyncMock(), added=[])
    db.add = db.added.append
    db.execute = AsyncMock(return_value=SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: rows)))
    async def find(_db, ent, contact_id):
        return next(r for r in rows if r.id == contact_id and r.enterprise_id == ent)
    monkeypatch.setattr(router, '_contact_or_404', find)
    monkeypatch.setattr(router, 'company_or_404', AsyncMock(return_value=SimpleNamespace(id=rows[0].company_id)))
    monkeypatch.setattr(router, 'lock_firm', AsyncMock())
    sub = SimpleNamespace(contacts=rows, items=[], cwt=[])
    monkeypatch.setattr(router, 'load_subledger', AsyncMock(return_value=sub))
    monkeypatch.setattr(router, '_contact_out', AsyncMock(return_value=rows[1]))
    user = User(id=rows[0].enterprise_id, email='e2e@example.test', role=UserRole.ENTERPRISE)
    return user, db


@pytest.mark.parametrize('archived_index', [0, 1])
def test_merge_router_refuses_archived_contact_before_writing(monkeypatch, archived_index):
    source, target = rows = contacts()
    rows[archived_index].archived_at = datetime.now(timezone.utc)
    user, db = contact_db(monkeypatch, rows)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(router.merge_contact(source.id, MergeIn(into=target.id), user=user, db=db))
    assert exc.value.status_code == 400 and 'Restore' in exc.value.detail
    assert source.merged_into_id is None and target.aliases == [] and db.added == []
    db.commit.assert_not_awaited()


def test_archive_restore_then_merge_preserves_identity_and_records_events(monkeypatch):
    source, target = rows = contacts()
    user, db = contact_db(monkeypatch, rows)
    asyncio.run(router.archive_contact(target.id, user=user, db=db))
    assert target.archived_at is not None
    asyncio.run(router.restore_contact(target.id, user=user, db=db))
    assert target.archived_at is None
    asyncio.run(router.merge_contact(source.id, MergeIn(into=target.id), user=user, db=db))
    assert source.merged_into_id == target.id
    assert resolve(source.key, rows) is target
    assert source.registered_name in target.aliases
    assert [e.action for e in db.added] == ['archive', 'restore', 'merge', 'merge_in']
    assert all(e.enterprise_id == user.id and e.company_id == target.company_id for e in db.added)


def test_restore_does_not_detach_a_merged_contact(monkeypatch):
    source, target = rows = contacts()
    source.merged_into_id = target.id
    source.archived_at = datetime.now(timezone.utc)
    user, db = contact_db(monkeypatch, rows)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(router.restore_contact(source.id, user=user, db=db))
    assert exc.value.status_code == 409 and source.archived_at is not None
    assert source.merged_into_id == target.id
    db.commit.assert_not_awaited()
