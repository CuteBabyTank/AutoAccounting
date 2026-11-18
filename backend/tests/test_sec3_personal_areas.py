"""Always-on lookups retain navigation without exposing disabled areas."""
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.models.user import UserRole
from app.routers import accounting_annual as annual, accounting_periods as periods
from app.schemas.accounting import AnnualInputsModel, AnnualPeriodOut, PeriodInputsModel, PeriodOut
from app.services import features


@pytest.fixture
def context(monkeypatch):
    user = SimpleNamespace(id=uuid.uuid4(), enterprise_id=uuid.uuid4(), role=UserRole.EMPLOYEE,
                           access={'off': ['filing', 'books']})
    company = SimpleNamespace(id=uuid.uuid4(), enterprise_id=user.enterprise_id, registered_name='Dummy',
                              tin='123456789', fiscal_year_end_month=12)

    async def company_lookup(*args):
        return company

    async def firm_switches(*args):
        return {key: True for key in features.KEYS}

    monkeypatch.setattr(periods, 'company_or_404', company_lookup)
    monkeypatch.setattr(annual, 'company_or_404', company_lookup)
    monkeypatch.setattr(features, 'firm_effective_for', firm_switches)
    return user, company


async def test_quarter_lookup_withholds_all_filing_fields(monkeypatch, context):
    user, company = context
    saved = PeriodOut(company=vars(company), year=2026, quarter=1, label='2026 Q1',
                      inputs=PeriodInputsModel(prior_taxable_income='12345.67'),
                      filed_at=datetime.now(timezone.utc), filed_forms={}, document_count=3, open_reviews=1,
                      latest_version=7, stale=True, books_stale=True, forms_expected=['1701Q'], due_dates={}, outputs=[])

    async def serialize(*args):
        return saved

    monkeypatch.setattr(periods, '_period_out', serialize)
    out = await periods.get_period(company.id, 2026, 1, user=user, db=None)
    assert out.inputs == PeriodInputsModel()
    assert out.filed_at is None and out.filed_forms == {}
    assert out.latest_version is None and not out.stale and not out.books_stale
    assert out.outputs == [] and out.forms_expected == [] and out.due_dates == {}
    assert out.company.id == company.id and out.document_count == 3


async def test_annual_lookup_keeps_its_own_gate_not_quarterly_filing(monkeypatch, context):
    # The annual route is gated by the 'annual' area; redacting on 'filing' made an annual-only person's save
    # overwrite saved credits and losses with defaults (review item 2). The fields must come back unchanged.
    user, company = context
    saved = AnnualPeriodOut(company=vars(company), year=2026, label='FY 2026', form='1701',
                            inputs=AnnualInputsModel(), filed_at=datetime.now(timezone.utc), document_count=3,
                            open_reviews=1, latest_version=7, stale=True, forms_expected=['1701'],
                            due_dates={}, outputs=[], carry_source='previous_year', previous_year_version=6,
                            has_compensation_income=True)

    async def serialize(*args):
        return saved

    monkeypatch.setattr(annual, '_annual_out', serialize)
    out = await annual.get_annual_period(company.id, 2026, user=user, db=None)
    assert out == saved


@pytest.mark.parametrize('off,expected', [(['books'], ['document']), (['documents'], ['opening']),
                                        (['books', 'documents'], [])])
async def test_asset_list_filters_each_assets_own_area(monkeypatch, context, off, expected):
    user, company = context
    user.access = {'off': off}
    rows = [(SimpleNamespace(document_id=None, description='opening'), None),
            (SimpleNamespace(document_id=uuid.uuid4(), description='document'), object())]

    class DB:
        async def execute(self, stmt):
            return SimpleNamespace(all=lambda: rows)

        async def commit(self):
            pass

    async def sync(*args):
        pass

    monkeypatch.setattr(annual, 'sync_assets', sync)
    monkeypatch.setattr(annual, '_asset_out', lambda row, *args: row.description)
    assert await annual.list_assets(company.id, 2026, user=user, db=DB()) == expected
