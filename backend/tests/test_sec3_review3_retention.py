"""Filed-quarter documents: ordinary corrections stay allowed; exclusion / moving retained history is refused
on every path (PATCH, bulk-resolve, move-company), and rematches leave retained bank lines alone."""

import uuid
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from app.models.accounting import AAAccount, AACompany, AAPeriod, AASupplierRule, AAWorkItem
from app.routers import accounting
from app.schemas.accounting import DocumentPatch
from app.services.accounting import move_company
from app.services.accounting.books import bank
from tests.test_sec3_match_retention import MatchDB, Result, stored


class Rows(Result):
    def first(self):
        return self.rows[0] if self.rows else None


class FiledDB(MatchDB):
    """MatchDB with Q2 2026 filed (no closed months) and a second company to move into."""

    def __init__(self):
        super().__init__()
        self.closes = []
        self.filed = [(2026, 2)]
        self.target = stored(AACompany, id=uuid.uuid4(), enterprise_id=self.user.id, registered_name="Other client",
                             tin="555444333", vat_status="non-vat", books_start=None)
        self.doc.review_reasons, self.doc.needs_review = ["receipt_incomplete"], True

    async def execute(self, stmt):
        desc = stmt.column_descriptions[0]
        entity, name = desc["entity"], desc["name"]
        if entity is AAPeriod and name == "year" and len(stmt.column_descriptions) == 2:  # filed quarters
            self.assert_locked()
            return Result(list(self.filed))
        if entity is AAWorkItem and name == "year":
            return Result([])
        if entity is AACompany and name == "AACompany":
            if self.target.id in stmt.compile().params.values():
                return Result([self.target])
        if entity is AACompany and name == "tin":
            return Result([])
        if entity is AAAccount and name == "company_id":
            return Result([])  # no locked accounts
        if entity is AASupplierRule:
            return Result([])
        if name == "id" and len(stmt.column_descriptions) == 1 and stmt._limit_clause is not None:
            return Rows([])  # MoveFacts' existence probes (asset / confirmed line / write-off / 2307): none here
        return await super().execute(stmt)

    def assert_locked(self):
        assert self.locked, "retention facts must be read under the firm lock"


async def _matched() -> FiledDB:
    db = FiledDB()
    assert await bank.rematch(db, db.company) == 1  # the real matcher links the March line to the document
    assert db.line.matched_ref == str(db.doc.id)
    return db


@pytest.mark.parametrize("edit", [{"seller_tin": "987654321"}, {"gl_account_code": "6900"},
                                  {"gross_amount": "1000"}, {"vat_amount": "10.71"}])
async def test_filed_quarter_document_accepts_ordinary_corrections(edit):
    db = await _matched()
    out = await accounting.patch_document(db.doc.id, DocumentPatch(**edit), user=db.user, db=db)
    assert out.id == db.doc.id and db.commits == 1 and db.audits
    # The line sits before the filed quarter (carried forward), so the rematch must not touch it.
    assert db.line.match_status == "matched" and db.line.matched_ref == str(db.doc.id)


async def test_filed_quarter_document_cannot_be_excluded_and_the_message_says_so():
    db = await _matched()
    with pytest.raises(HTTPException) as error:
        await accounting.patch_document(db.doc.id, DocumentPatch(excluded=True), user=db.user, db=db)
    assert error.value.status_code == 409
    assert "filed return" in error.value.detail and "instead of excluding it" in error.value.detail
    assert "deleting" not in error.value.detail
    assert not db.doc.excluded and db.commits == 0 and not db.audits


async def test_bulk_resolve_exclude_skips_retained_documents_without_unmatching_history():
    db = await _matched()
    body = accounting.BulkResolveIn(document_ids=[db.doc.id], reason_code="receipt_incomplete",
                                    action="exclude", reason="Not a BIR receipt")
    out = await accounting.bulk_resolve(body, user=db.user, db=db)
    assert out["resolved"] == []
    assert out["skipped"][0]["id"] == str(db.doc.id) and "excluding it" in out["skipped"][0]["why"]
    assert not db.doc.excluded and not db.audits
    assert db.line.match_status == "matched" and db.line.matched_ref == str(db.doc.id)
    # The follow-up delete from the review scenario is refused too: the stored link survived.
    with pytest.raises(HTTPException) as error:
        await accounting.delete_document(db.doc.id, user=db.user, db=db)
    assert error.value.status_code == 409 and db.doc.deleted_at is None

    # Without retained history the same bulk exclusion goes through and the real rematch runs.
    db.filed = []
    out = await accounting.bulk_resolve(body, user=db.user, db=db)
    assert out["resolved"] == [str(db.doc.id)] and db.doc.excluded
    assert db.line.matched_ref == ""


async def test_move_company_refuses_a_retained_document():
    db = await _matched()
    with pytest.raises(HTTPException) as error:
        await accounting.move_document_to_company(db.doc.id, accounting.MoveCompanyIn(company_id=db.target.id),
                                                  user=db.user, db=db)
    assert error.value.status_code == 409 and "instead of moving it to another company" in error.value.detail
    assert db.doc.company_id == db.company.id and db.commits == 0 and not db.audits
    assert db.line.matched_ref == str(db.doc.id)


async def test_upload_move_lists_retained_document_as_refused():
    # The upload-level move uses the same per-document step; a refusal is reported, nothing moves.
    db = await _matched()
    to = await accounting._move_target(db, db.user.id, db.target)
    problem = await accounting._move_document(db, db.user.id, db.user, db.doc, db.company, to)
    assert problem and "filed return" in problem
    assert db.doc.company_id == db.company.id and not db.audits


def test_move_facts_retained_history_is_reported_after_statements():
    assert move_company.move_problem(move_company.MoveFacts(retained_history="March 2026 is closed.")) \
        == "March 2026 is closed."
    assert "Bank statements" in move_company.move_problem(
        move_company.MoveFacts(is_statement=True, retained_history="x"))
    assert move_company.move_problem(move_company.MoveFacts()) is None


async def test_safe_line_ids_excludes_confirmed_closed_filed_and_reconciled_lines():
    from app.services.accounting import deletion

    db = FiledDB()
    assert await deletion.safe_line_ids(db, db.company) == set()  # March, before filed Q2
    db.filed = []
    assert await deletion.safe_line_ids(db, db.company) == {db.line.id}
    db.line.match_status = "confirmed"
    assert await deletion.safe_line_ids(db, db.company) == set()
    db.line.match_status = "unmatched"
    db.closes = [(datetime(2026, 3, 1, tzinfo=timezone.utc).date(), datetime(2026, 3, 31).date())]
    assert await deletion.safe_line_ids(db, db.company) == set()
