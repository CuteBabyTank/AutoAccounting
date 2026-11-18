"""Edits to a document whose bank line retained history holds (closed / filed / reconciled, so the rematch keeps
its match): changing the document's side is refused, a receipt's amount voids the line's reconciliation, plain
invoice amounts stay editable, and automatic receipt links in retained history are not moved by the relink."""

import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.models.accounting import AABankReconciliation
from app.routers import accounting
from app.schemas.accounting import DocumentPatch
from app.services.accounting.books import bank
from app.services.accounting.books.links import plan_links
from tests.test_sec3_match_retention import MatchDB, Result


class RecDB(MatchDB):
    """MatchDB (March 2026 closed, the line on 31 March) plus live reconciliations of account 1020."""

    def __init__(self, recs=True):
        super().__init__()
        self.recs = [SimpleNamespace(account_code="1020", month_end=end, voided_at=None)
                     for end in (date(2026, 3, 31), date(2026, 4, 30))] if recs else []

    async def execute(self, stmt):
        if stmt.column_descriptions[0]["entity"] is AABankReconciliation:
            assert self.locked
            return Result([r for r in self.recs if r.voided_at is None])
        return await super().execute(stmt)


async def _matched(db: MatchDB) -> MatchDB:
    assert await bank.rematch(db, db.company) == 1
    assert db.line.matched_ref == str(db.doc.id)
    return db


@pytest.mark.parametrize("db", [MatchDB(), RecDB()], ids=["closed-month", "reconciled"])
async def test_type_change_is_refused_while_a_held_line_is_matched(db):
    await _matched(db)
    if isinstance(db, RecDB):  # held only by a live reconciliation: no closed month
        db.closes = []
        for rec in db.recs:
            rec.voided_at = None
    with pytest.raises(HTTPException) as error:
        await accounting.patch_document(db.doc.id, DocumentPatch(category="sales"), user=db.user, db=db)
    assert error.value.status_code == 409
    assert "Undo the bank match" in error.value.detail and "changing its type" in error.value.detail
    assert db.doc.category == "expenses" and db.commits == 0 and not db.audits
    assert db.line.matched_ref == str(db.doc.id)


async def test_type_change_is_allowed_when_no_held_line_is_matched():
    db = await _matched(MatchDB())
    db.closes = []  # March reopened: the line is safe again, so the rematch may re-decide it
    out = await accounting.patch_document(db.doc.id, DocumentPatch(category="purchases"), user=db.user, db=db)
    assert out.category == "purchases" and db.commits == 1 and db.audits


async def test_same_category_resent_is_not_a_type_change():
    db = await _matched(MatchDB())
    await accounting.patch_document(db.doc.id, DocumentPatch(category="expenses", notes="ok"), user=db.user, db=db)
    assert db.commits == 1 and db.line.matched_ref == str(db.doc.id)


def _receipt(db: MatchDB) -> None:
    db.doc.doc_type, db.doc.document_title = "receipt", "Official Receipt"
    db.doc.settles_document_id, db.doc.settles_source = uuid.uuid4(), "auto"
    db.line.match_status, db.line.match_kind = "matched", "document"
    db.line.matched_ref, db.line.match_amount = str(db.doc.id), Decimal("100")


async def test_receipt_amount_change_voids_the_held_lines_reconciliation():
    db = RecDB()
    _receipt(db)
    invoice = db.doc.settles_document_id
    out = await accounting.patch_document(db.doc.id, DocumentPatch(gross_amount="150"), user=db.user, db=db)
    assert out.gross_amount == Decimal("150") and db.commits == 1 and db.audits
    assert all(r.voided_at is not None for r in db.recs)
    assert db.company.books_updated_at is not None
    # The held match stays, and the frozen receipt keeps its automatic link through the relink.
    assert db.line.matched_ref == str(db.doc.id) and db.doc.settles_document_id == invoice


async def test_invoice_amount_edit_is_allowed_and_keeps_the_held_match_and_reconciliation():
    db = await _matched(RecDB())
    for rec in db.recs:  # reconciled after the match was made
        rec.voided_at = None
    out = await accounting.patch_document(db.doc.id, DocumentPatch(gross_amount="150"), user=db.user, db=db)
    assert out.gross_amount == Decimal("150") and db.commits == 1 and db.audits
    assert db.line.match_status == "matched" and db.line.matched_ref == str(db.doc.id)
    assert all(r.voided_at is None for r in db.recs)


async def test_relink_leaves_an_automatic_receipt_link_in_closed_history_alone():
    db = MatchDB()
    _receipt(db)
    db.line.match_status, db.line.matched_ref = "unmatched", ""  # only the receipt's closed March date holds it
    db.doc.doc_date, db.doc.period_quarter = date(2026, 3, 15), 1
    invoice = db.doc.settles_document_id
    await accounting.patch_document(db.doc.id, DocumentPatch(seller_name="Acme Widgets Inc."), user=db.user, db=db)
    # Its invoice isn't among the live invoices, so an unguarded relink would have unlinked it.
    assert db.doc.settles_document_id == invoice and db.doc.settles_source == "auto"
    db.closes = []
    await accounting.patch_document(db.doc.id, DocumentPatch(seller_name="Acme Widgets"), user=db.user, db=db)
    assert db.doc.settles_document_id is None


def _doc(kind: str, **values):
    return SimpleNamespace(**({"id": uuid.uuid4(), "deleted_at": None, "excluded": False, "client_role": "buyer",
                               "seller_tin": "123456789", "seller_name": "Acme", "buyer_tin": "", "buyer_name": "",
                               "doc_date": date(2026, 4, 1), "gross_amount": Decimal("100"),
                               "withholding_amount": Decimal("0"), "settles_document_id": None, "settles_source": "",
                               "category": "expenses", "doc_type": kind,
                               "document_title": "Invoice" if kind == "invoice" else "Official Receipt"} | values))


def test_plan_links_keeps_frozen_receipts_and_held_invoices_out_of_reach():
    invoice = _doc("invoice")
    receipt = _doc("receipt", doc_date=date(2026, 4, 5))
    assert plan_links([invoice, receipt])[str(receipt.id)].settles == str(invoice.id)
    assert str(receipt.id) not in plan_links([invoice, receipt], frozen={str(receipt.id)})
    assert plan_links([invoice, receipt], held_invoices={str(invoice.id)})[str(receipt.id)].settles is None


@pytest.mark.parametrize("caller", ["pipeline", "move"])
async def test_non_patch_callers_keep_a_closed_month_automatic_receipt_link(caller):
    """relink_receipts guards itself, so the pipeline's relink (firm lock, then relink) and the move-company
    refresh leave a closed-month receipt linked although its invoice isn't among the live invoices."""
    from app.services.accounting.assignment import lock_firm
    from app.services.accounting.books.links import relink_receipts

    db = MatchDB()
    _receipt(db)
    db.line.match_status, db.line.matched_ref = "unmatched", ""
    db.doc.doc_date, db.doc.period_quarter = date(2026, 3, 15), 1
    invoice = db.doc.settles_document_id

    async def relink():
        await lock_firm(db, db.user.id)
        if caller == "pipeline":
            await relink_receipts(db, db.company.id)
        else:
            await accounting._refresh_after_move(db, [db.company])

    await relink()
    assert db.doc.settles_document_id == invoice and db.doc.settles_source == "auto"
    db.closes = []  # reopened: the same relink now re-decides the link
    await relink()
    assert db.doc.settles_document_id is None
