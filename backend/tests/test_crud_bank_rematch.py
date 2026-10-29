"""A selective rule rematch must reserve payments and preserve every unrelated historical line."""
import asyncio
import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.services.accounting.books import bank, loader


def test_selective_rematch_reserves_unchanged_automatic_payment(monkeypatch):
    ref = str(uuid.uuid4())
    reserved = SimpleNamespace(id=uuid.uuid4(), match_status='matched', matched_ref=ref,
                               match_amount=Decimal('100'), amount=Decimal('-100'))
    changing = SimpleNamespace(id=uuid.uuid4(), match_status='unmatched', matched_ref='', amount=Decimal('-100'),
                               line_date=date(2026, 3, 1), narration='E2E RENT', check_no='', account_code='1020',
                               rejected=[])
    db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(
        scalars=lambda: SimpleNamespace(all=lambda: [reserved, changing]))), flush=AsyncMock())
    company = SimpleNamespace(id=uuid.uuid4(), enterprise_id=uuid.uuid4())
    candidates = AsyncMock(return_value=[])
    monkeypatch.setattr(bank, '_documents', AsyncMock(return_value=[]))
    monkeypatch.setattr(bank, '_candidates', candidates)
    monkeypatch.setattr(loader, 'ensure_chart', AsyncMock(return_value=SimpleNamespace()))
    monkeypatch.setattr(bank, 'bank_accounts', AsyncMock(return_value=[]))
    monkeypatch.setattr(bank, 'company_rules', AsyncMock(return_value=[]))
    monkeypatch.setattr(bank, '_flushed_paid_ids', AsyncMock(return_value=set()))
    monkeypatch.setattr(bank, 'refresh_opening_flag', AsyncMock())
    asyncio.run(bank.rematch(db, company, line_ids={changing.id}))
    assert candidates.await_args.args[3] == {ref: Decimal('100.00')}
    assert candidates.await_args.args[4] == {ref}
    assert reserved.match_status == 'matched' and reserved.matched_ref == ref
    assert changing.match_status == 'unmatched'
