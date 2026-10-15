import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.services.accounting.books.links import plan_links


def _d(title, doc_type, gross, on, **kw):
    values = dict(id=uuid.uuid4(), document_title=title, doc_type=doc_type, category="sales", client_role="seller",
                  doc_date=on, gross_amount=Decimal(gross), withholding_amount=Decimal("0"), buyer_tin="555666777",
                  buyer_name="Customer", seller_tin="123456789", seller_name="Client", settles_document_id=None,
                  settles_source="", deleted_at=None, excluded=False)
    values.update(kw)
    return SimpleNamespace(**values)


def test_auto_link_and_clear_when_no_longer_matching():
    invoice = _d("SALES INVOICE", "invoice", "1120", date(2026, 7, 1))
    receipt = _d("COLLECTION RECEIPT", "receipt", "1120", date(2026, 7, 9))
    plan = plan_links([invoice, receipt])
    assert plan[str(receipt.id)].settles == str(invoice.id) and plan[str(receipt.id)].source == "auto"

    receipt.settles_document_id, receipt.settles_source = invoice.id, "auto"
    receipt.gross_amount = Decimal("999")
    plan = plan_links([invoice, receipt])
    assert plan[str(receipt.id)].settles is None and plan[str(receipt.id)].source == ""


def test_user_decisions_are_kept_and_their_invoice_is_taken():
    invoice = _d("SALES INVOICE", "invoice", "500", date(2026, 7, 1))
    mine = _d("OFFICIAL RECEIPT", "receipt", "500", date(2026, 7, 2), settles_document_id=None, settles_source="user")
    other = _d("OFFICIAL RECEIPT", "receipt", "500", date(2026, 7, 3))
    plan = plan_links([invoice, mine, other])
    assert str(mine.id) not in plan                       # a person decided: left alone
    assert plan[str(other.id)].settles == str(invoice.id)

    mine.settles_document_id = invoice.id
    plan = plan_links([invoice, mine, other])
    assert plan[str(other.id)].settles is None            # the invoice is already paid by a user link


def test_several_candidates_flag_possible_payment():
    a = _d("SALES INVOICE", "invoice", "500", date(2026, 7, 1))
    b = _d("SALES INVOICE", "invoice", "500", date(2026, 7, 2))
    r = _d("OFFICIAL RECEIPT", "receipt", "500", date(2026, 7, 9))
    change = plan_links([a, b, r])[str(r.id)]
    assert change.settles is None and change.possible


def test_deleted_and_excluded_documents_are_ignored():
    invoice = _d("SALES INVOICE", "invoice", "500", date(2026, 7, 1), excluded=True)
    r = _d("OFFICIAL RECEIPT", "receipt", "500", date(2026, 7, 9))
    assert plan_links([invoice, r])[str(r.id)].settles is None
