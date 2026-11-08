"""Review regressions: run handlers and retention/billing logic with only persistence replaced."""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.models.accounting import (
    AAAsset, AAAuditEvent, AABankLine, AABookClose, AACompany, AADocument,
    AAImportBatch, AAOpeningItem, AAPeriod, AAWorkItem,
)
from app.models.user import User, UserRole
from app.routers import accounting, accounting_annual, accounting_imports
from app.schemas.accounting import CompanyIn, DocumentPatch
from app.services import features


class Rows:
    def __init__(self, rows: list):
        self.rows = rows

    def __iter__(self):
        return iter(self.rows)

    def scalars(self) -> "Rows":
        return self

    def all(self) -> list:
        return self.rows

    def scalar_one_or_none(self):
        return self.rows[0] if self.rows else None

    def one(self):
        return self.rows[0]


def context() -> tuple[User, AACompany]:
    owner = User(id=uuid.uuid4(), role=UserRole.ENTERPRISE, email="owner@example.test")
    company = AACompany(id=uuid.uuid4(), enterprise_id=owner.id, review_flags={},
                        **CompanyIn(registered_name="Fixture", tin="123456789").model_dump())
    return owner, company


class HistoryDb:
    def __init__(self, owner: User, company: AACompany) -> None:
        self.owner, self.company = owner, company
        self.doc: AADocument | None = None
        self.batch: AAImportBatch | None = None
        self.items: list[AAOpeningItem] = []
        self.lines: list[AABankLine] = []
        self.filed: list[tuple[int, int]] = []
        self.board: list[tuple[int, int]] = []
        self.closes: list[tuple[date, date]] = []
        self.period: AAPeriod | None = None
        self.events: list[AAAuditEvent] = []
        self.commits = 0

    async def execute(self, stmt) -> Rows:
        entity = stmt.column_descriptions[0]["entity"]
        if entity is User:
            return Rows([self.owner])
        if entity is AACompany:
            return Rows([self.company])
        if entity is AADocument:
            if stmt.column_descriptions[0]["name"] == "count":
                return Rows([(1, 0)])
            return Rows([self.doc] if self.doc else [])
        if entity is AABankLine:
            # The first opening item is intentionally clear; the second owns the January payment.
            if self.items and str(self.items[0].id) in str(stmt.compile().params):
                refs = str(stmt.compile().params)
                if str(self.items[1].id) not in refs:
                    return Rows([])
            return Rows(self.lines)
        if entity is AAImportBatch:
            return Rows([self.batch])
        if entity is AAOpeningItem:
            return Rows(self.items)
        if entity is AAPeriod:
            if self.period:
                return Rows([self.period] if stmt.compile().params.get("year_1") == 2026 else [])
            if len(stmt.column_descriptions) == 4:
                return Rows([(y, q, datetime.now(timezone.utc), {}) for y, q in self.filed])
            return Rows(self.filed)
        if entity is AAWorkItem:
            return Rows(self.board)
        if entity is AABookClose:
            return Rows(self.closes)
        if entity is AAAsset:
            return Rows([])
        return Rows([])

    def add(self, event: AAAuditEvent) -> None:
        # Refusal must happen before the first source or audit mutation, including the clear item.
        if self.doc:
            assert self.doc.doc_date == date(2026, 4, 2), "PATCH erased history before checking bank links"
        if self.items:
            assert all(i.deleted_at is None for i in self.items), "undo mutated a batch before all guards passed"
        self.events.append(event)

    async def flush(self) -> None:
        if self.items:
            assert all(i.deleted_at is None for i in self.items), "undo mutated a batch before all guards passed"

    async def commit(self) -> None:
        self.commits += 1


async def test_annual_only_read_modify_save_preserves_saved_credits_and_losses() -> None:
    owner, company = context()
    user = User(id=uuid.uuid4(), enterprise_id=owner.id, role=UserRole.EMPLOYEE, email="annual@example.test",
                access={"off": ["filing"]})
    db = HistoryDb(owner, company)
    db.period = AAPeriod(id=uuid.uuid4(), company_id=company.id, enterprise_id=owner.id, year=2026, quarter=0,
                         inputs={"prior_year_excess_credits": "1200.00",
                                 "opening_nolco": [{"year": 2025, "amount": "5000.00", "used": "100.00"}]})
    features.invalidate()
    request = Request({"type": "http", "method": "GET", "headers": [],
                       "path": f"/api/accounting/periods/{company.id}/2026/annual"})
    await features.feature_gate(request, user=user, db=db)
    out = await accounting_annual.get_annual_period(company.id, 2026, user=user, db=db)
    assert out.inputs.prior_year_excess_credits == Decimal("1200.00")
    assert out.inputs.opening_nolco[0].amount == Decimal("5000.00")
    out.inputs.non_operating_income = Decimal("99.00")
    await accounting_annual.save_annual_inputs(out.inputs, company.id, 2026, user=user, db=db)
    assert db.period.inputs["prior_year_excess_credits"] == "1200.00"
    assert db.period.inputs["opening_nolco"][0]["amount"] == "5000.00"
    assert db.events[-1].action == "inputs" and db.commits == 1
    user.access = {"off": ["annual"]}
    with pytest.raises(HTTPException) as exc:
        await features.feature_gate(request, user=user, db=db)
    assert exc.value.status_code == 403
    features.invalidate()


@pytest.mark.parametrize("history", ["closed-bank-month", "later-filed", "board-filed"])
async def test_patch_cannot_erase_history_reached_through_bank_links(history: str) -> None:
    owner, company = context()
    db = HistoryDb(owner, company)
    db.doc = AADocument(id=uuid.uuid4(), company_id=company.id, enterprise_id=owner.id,
                        doc_date=date(2026, 4, 2), paid_on=None, period_year=2026, period_quarter=2,
                        category="support", doc_type="other", doc_number="D1", seller_name="Fixture",
                        review_reasons=[], review_notes={}, period_locked=True)
    db.lines = [AABankLine(id=uuid.uuid4(), company_id=company.id, enterprise_id=owner.id,
                           line_date=date(2026, 3, 31), match_status="matched", match_kind="document",
                           matched_ref=str(db.doc.id), account_code="1010")]
    if history == "closed-bank-month":
        db.closes = [(date(2026, 3, 1), date(2026, 3, 31))]
    elif history == "later-filed":
        db.filed = [(2026, 1)]
    else:
        db.board = [(2026, 1)]
    with pytest.raises(HTTPException) as exc:
        await accounting.patch_document(db.doc.id, DocumentPatch(doc_date=None, period_year=None,
                                                                 period_quarter=None), user=owner, db=db)
    assert exc.value.status_code == 409
    assert db.doc.doc_date == date(2026, 4, 2) and db.doc.period_quarter == 2
    assert not db.events and db.commits == 0


@pytest.mark.parametrize("board", [False, True])
async def test_opening_item_undo_checks_later_filings_before_any_item_mutates(board: bool) -> None:
    owner, company = context()
    db = HistoryDb(owner, company)
    db.batch = AAImportBatch(id=uuid.uuid4(), company_id=company.id, enterprise_id=owner.id,
                             kind="open-items", filename="items.csv", created_by=owner.id, undone_at=None)
    db.items = [AAOpeningItem(id=uuid.uuid4(), company_id=company.id, enterprise_id=owner.id,
                              import_batch_id=db.batch.id, doc_number=f"O{i}", paid_on=None, deleted_at=None)
                for i in range(2)]
    db.lines = [AABankLine(id=uuid.uuid4(), company_id=company.id, enterprise_id=owner.id,
                           line_date=date(2026, 1, 31), match_status="matched",
                           match_kind="document", matched_ref=str(db.items[1].id), account_code="1010")]
    if board:
        db.board = [(2026, 2)]
    else:
        db.filed = [(2026, 2)]
    with pytest.raises(HTTPException) as exc:
        await accounting_imports.undo_import(db.batch.id, user=owner, db=db)
    assert exc.value.status_code == 409
    assert all(i.deleted_at is None for i in db.items)
    assert db.batch.undone_at is None and not db.events and db.commits == 0


