"""Pending accepted pages consume admission headroom before reader work begins."""
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.models.accounting import AAExtractFile
from app.models.user import UserRole
from app.services import usage_service as billing
from app.routers import accounting


def pages_of(stmt, upload_pages, extract_pages=()):
    """Reservation reads: unread upload pages, then unread Extract pages (a separate query)."""
    rows = list(extract_pages) if stmt.column_descriptions[0]["entity"] is AAExtractFile else list(upload_pages)
    return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: rows))


async def test_positive_budget_cannot_admit_a_larger_page_batch(monkeypatch):
    enterprise = SimpleNamespace(id=uuid.uuid4(), budget=0.01, usage_cap=None, global_usage_cap=None)
    pending = [2, 2, 2, 2]
    locks = []

    class DB:
        async def refresh(self, row, **kwargs):
            locks.append(kwargs.get('with_for_update'))

        async def execute(self, stmt):
            return pages_of(stmt, pending)

    async def owner(*args):
        return enterprise

    async def config(*args):
        return 1.0, None

    async def usage(*args):
        return SimpleNamespace(pages_used=0)

    monkeypatch.setattr(accounting, 'get_enterprise_for_user', owner)
    monkeypatch.setattr(billing, 'get_effective_rate_config', config)
    monkeypatch.setattr(billing, 'get_or_create_usage', usage)
    # Older code imports this name directly; also configure that alias for the pre-fix regression.
    monkeypatch.setattr(accounting, 'get_effective_rate_config', config, raising=False)
    with pytest.raises(HTTPException) as error:
        await accounting._assert_budget(DB(), SimpleNamespace(role=UserRole.EMPLOYEE))
    assert error.value.status_code == 402
    assert 'budget' in error.value.detail.lower()
    assert locks == [True]


async def test_pending_batches_compete_for_the_same_remaining_balance(monkeypatch):
    enterprise = SimpleNamespace(id=uuid.uuid4(), budget=5.0, usage_cap=None, global_usage_cap=None)
    pending = [3]

    class DB:
        async def refresh(self, row, **kwargs):
            pass

        async def execute(self, stmt):
            return pages_of(stmt, pending)

    async def config(*args):
        return 1.0, None

    async def usage(*args):
        return SimpleNamespace(pages_used=0)

    monkeypatch.setattr(billing, 'get_effective_rate_config', config)
    monkeypatch.setattr(billing, 'get_or_create_usage', usage)
    # A committed batch keeps its reservation without debiting (or double-charging) budget.
    await billing.assert_pending_page_budget(DB(), enterprise)
    pending.append(3)
    with pytest.raises(ValueError, match='budget'):
        await billing.assert_pending_page_budget(DB(), enterprise)
    assert enterprise.budget == 5.0


async def test_unread_extract_pages_hold_budget_for_uploads_too(monkeypatch):
    """Uploads and Extract runs share one pending set: an upload can't take budget an Extract run has reserved."""
    enterprise = SimpleNamespace(id=uuid.uuid4(), budget=5.0, usage_cap=None, global_usage_cap=None)

    class DB:
        def __init__(self, uploads, extracts):
            self.uploads, self.extracts = uploads, extracts

        async def refresh(self, row, **kwargs):
            assert kwargs.get('with_for_update')

        async def execute(self, stmt):
            return pages_of(stmt, self.uploads, self.extracts)

    async def config(*args):
        return 1.0, None

    async def usage(*args):
        return SimpleNamespace(pages_used=0)

    monkeypatch.setattr(billing, 'get_effective_rate_config', config)
    monkeypatch.setattr(billing, 'get_or_create_usage', usage)
    await billing.assert_pending_page_budget(DB([3], []), enterprise)
    with pytest.raises(ValueError, match='budget'):
        await billing.assert_pending_page_budget(DB([3], [3]), enterprise)   # an upload after an Extract run
    with pytest.raises(ValueError, match='budget'):
        await billing.assert_pending_page_budget(DB([], [3, 3]), enterprise)  # two Extract runs


def test_tier_reservation_covers_any_order_of_free_page_consumption():
    tiers = [{'up_to': 2, 'rate': 3.0}, {'up_to': None, 'rate': 1.0}]
    # Three free pages: depending on which document finishes first, actual cost is 3 or 6.
    assert billing.page_batch_reservation([1, 4], 3, None, tiers) >= 6.0
    assert billing.page_batch_reservation([1, 4], 5, None, tiers) == 0.0
    assert billing.page_batch_reservation([3, 3], 2, 1.0, None) == 4.0
    assert billing.page_batch_reservation([3, 3], 0, None, None) == 0.0


@pytest.mark.parametrize('flat,cap', [(None, None), (1.0, 100)])
async def test_billing_off_or_free_allowance_allows_zero_balance(monkeypatch, flat, cap):
    enterprise = SimpleNamespace(id=uuid.uuid4(), budget=0.0, usage_cap=cap, global_usage_cap=None)

    class DB:
        async def refresh(self, row, **kwargs):
            pass

        async def execute(self, stmt):
            return pages_of(stmt, [8])

    async def owner(*args):
        return enterprise

    async def config(*args):
        return flat, None

    async def usage(*args):
        return SimpleNamespace(pages_used=0)

    monkeypatch.setattr(accounting, 'get_enterprise_for_user', owner)
    monkeypatch.setattr(billing, 'get_effective_rate_config', config)
    monkeypatch.setattr(accounting, 'get_effective_rate_config', config, raising=False)
    monkeypatch.setattr(billing, 'get_or_create_usage', usage)
    await accounting._assert_budget(DB(), SimpleNamespace(role=UserRole.EMPLOYEE))


async def test_create_upload_refuses_before_commit_or_detection(monkeypatch, tmp_path):
    from unittest.mock import AsyncMock, Mock
    from app.models.accounting import AAFile

    owner = SimpleNamespace(id=uuid.uuid4(), role=UserRole.ENTERPRISE, budget=0.01,
                            usage_cap=None, global_usage_cap=None)
    rows = []

    class DB:
        commit = AsyncMock()
        rollback = AsyncMock()
        flush = AsyncMock()
        refresh = AsyncMock()

        def add(self, row):
            rows.append(row)

        async def get(self, model, ident):
            return next(row for row in rows if isinstance(row, model))

        async def execute(self, stmt):
            pages = [row.page_count for row in rows if isinstance(row, AAFile) and row.status == 'uploaded']
            return pages_of(stmt, pages)

    async def config(*args):
        return 1.0, None

    stored = SimpleNamespace(filename='dummy.pdf', stored_path=str(tmp_path / 'dummy.pdf'),
                             file_type='pdf', size=100, sha256='a' * 64, page_count=8)
    monkeypatch.setattr(accounting.settings, 'environment', 'development')
    monkeypatch.setattr(accounting.accounting_upload_limiter, 'check_and_record', lambda *args: True)
    monkeypatch.setattr(accounting, 'upload_dir', lambda *args: tmp_path)
    monkeypatch.setattr(accounting, 'stream_upload', AsyncMock(return_value=stored))
    monkeypatch.setattr(accounting, '_upload_out', AsyncMock(return_value=object()))
    monkeypatch.setattr(accounting.pipeline, 'start_detection', Mock())
    monkeypatch.setattr(accounting.audit, 'record', Mock())
    monkeypatch.setattr(billing, 'get_effective_rate_config', config)
    monkeypatch.setattr(accounting, 'get_effective_rate_config', config, raising=False)
    monkeypatch.setattr(billing, 'get_or_create_usage', AsyncMock(return_value=SimpleNamespace(pages_used=0)))
    db = DB()
    with pytest.raises(HTTPException) as error:
        await accounting.create_upload([object()], company_id=None, shrunk=[], user=owner, db=db)
    assert error.value.status_code == 402
    db.commit.assert_not_awaited()
    db.rollback.assert_awaited_once()
    accounting.pipeline.start_detection.assert_not_called()


async def test_confirm_rechecks_budget_before_extraction(monkeypatch):
    from unittest.mock import AsyncMock, Mock
    from app.models.accounting import AACompany

    owner = SimpleNamespace(id=uuid.uuid4(), role=UserRole.ENTERPRISE, budget=0.01,
                            usage_cap=None, global_usage_cap=None)
    company_id, upload_id = uuid.uuid4(), uuid.uuid4()
    file = SimpleNamespace(id=uuid.uuid4(), page_count=8, status='detected', original_filename='dummy.pdf')
    upload = SimpleNamespace(status='awaiting_confirmation')

    class DB:
        commit = AsyncMock()
        rollback = AsyncMock()
        flush = AsyncMock()
        refresh = AsyncMock()

        async def get(self, model, ident):
            return upload

        async def execute(self, stmt):
            if getattr(stmt, 'is_update', False):
                return SimpleNamespace(rowcount=1)
            column = stmt.column_descriptions[0]
            if column['entity'] is AACompany:
                return SimpleNamespace(scalars=lambda: [company_id])
            if column['entity'] is AAExtractFile:
                return pages_of(stmt, [], [])
            rows = [8] if column['name'] == 'page_count' else [file]
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: rows))

    async def config(*args):
        return 1.0, None

    monkeypatch.setattr(billing, 'get_effective_rate_config', config)
    monkeypatch.setattr(billing, 'get_or_create_usage', AsyncMock(return_value=SimpleNamespace(pages_used=0)))
    monkeypatch.setattr(accounting.pipeline, 'start_extraction', Mock())
    monkeypatch.setattr(accounting.audit, 'record', Mock())
    monkeypatch.setattr(accounting, '_upload_out', AsyncMock(return_value=object()))
    db = DB()
    body = accounting.ConfirmIn(assignments=[{'file_ids': [file.id], 'company_id': company_id}])
    with pytest.raises(HTTPException) as error:
        await accounting.confirm_upload(upload_id, body, user=owner, db=db)
    assert error.value.status_code == 402
    db.commit.assert_not_awaited()
    accounting.pipeline.start_extraction.assert_not_called()
