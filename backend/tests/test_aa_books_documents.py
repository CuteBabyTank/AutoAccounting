import uuid
from datetime import date
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.routers.accounting_periods import counts_on_returns, doc_line
from app.schemas.accounting import DocumentPatch
from app.services.accounting.assets import is_asset_document


def _doc(**kw):
    values = dict(
        id=uuid.uuid4(), category="purchases", account="capital_goods", doc_type="invoice", client_role="buyer",
        doc_date=date(2026, 7, 1), doc_number="1", seller_tin="111222333", seller_name="S", seller_address="",
        buyer_tin="", buyer_name="", buyer_address="", gross_amount=0, vatable_amount=0, vat_amount=0,
        exempt_amount=0, zero_rated_amount=0, withholding_amount=0, input_vat_valid=None, needs_review=False,
        reviewed=False, ewt_atc="", seller_vat_registered=None, gl_account_code="", settles_document_id=None,
        deleted_at=None, excluded=False, raw=None,
    )
    values.update(kw)
    return SimpleNamespace(**values)


def test_linked_receipt_is_left_out_of_returns():
    assert counts_on_returns(_doc())
    assert not counts_on_returns(_doc(settles_document_id=uuid.uuid4()))


def test_linked_receipt_is_not_an_asset():
    assert is_asset_document(_doc())
    assert not is_asset_document(_doc(settles_document_id=uuid.uuid4()))


def test_doc_line_carries_gl_override_or_remembered_rule():
    assert doc_line(_doc(gl_account_code="6021")).gl_account == "6021"
    assert doc_line(_doc(), gl_rules={"111222333": "6022"}).gl_account == "6022"
    assert doc_line(_doc(gl_account_code="6021"), gl_rules={"111222333": "6022"}).gl_account == "6021"


def test_document_patch_payment_fields():
    p = DocumentPatch(paid_on=date(2026, 7, 9), paid_via="bank", payment_ref="CHK 001", gl_account_code="6021",
                      settles_document_id=uuid.uuid4())
    assert p.paid_via == "bank"
    assert DocumentPatch(paid_on=None).model_fields_set == {"paid_on"}
    with pytest.raises(ValidationError):
        DocumentPatch(paid_via="gcash")
    with pytest.raises(ValidationError):
        DocumentPatch(gl_account_code="12345678901")
