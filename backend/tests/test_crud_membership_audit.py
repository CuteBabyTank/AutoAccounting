import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.models.user import User, UserRole
from app.routers import team


def test_unlink_preserves_account_and_records_firm_scoped_before_after(monkeypatch):
    owner = User(id=uuid.uuid4(), role=UserRole.ENTERPRISE, email='e2e-owner@example.test')
    member = User(id=uuid.uuid4(), role=UserRole.EMPLOYEE, enterprise_id=owner.id,
                  email='e2e-member@example.test', is_active=True)
    monkeypatch.setattr(team, '_member_or_404', AsyncMock(return_value=member))
    events = []
    db = SimpleNamespace(add=events.append, commit=AsyncMock())
    asyncio.run(team.remove_member(member.id, db=db, ctx=SimpleNamespace(caller=owner, enterprise=owner)))
    assert member.enterprise_id is None and member.role == UserRole.UNVERIFIED
    assert events[0].enterprise_id == owner.id and events[0].user_id == owner.id
    assert events[0].before['enterprise_id'] == str(owner.id)
    assert events[0].after['enterprise_id'] is None
    assert events[0].entity == 'team_member' and events[0].action == 'delete'
    db.commit.assert_awaited_once()
