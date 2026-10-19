from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.services.accounting.classify import CompanyProfile, classify_document
from app.services.accounting.extraction import ExtractedDoc, Party
from app.services.accounting.review_rules import RECEIPT_REASON, receipt_problems, sync_receipt_flag

COMPANY = CompanyProfile("010234567", "Bayanihan Hardware Trading Corp.", (), False, 12)
CLIENT = Party(name="Bayanihan Hardware Trading Corp.", tin="010234567")
SUPPLIER = Party(name="Golden Hardware Wholesale", tin="111222333", address="12 Rizal Ave, Marikina")


def _ext(**kw) -> ExtractedDoc:
    base = dict(document_title="SALES INVOICE", kind="invoice", doc_number="8098", doc_date=date(2026, 8, 14),
                seller=SUPPLIER, buyer=CLIENT, gross_amount=Decimal("560.00"), exempt_amount=Decimal("0"),
                nature="other", expense_account="office_supplies", confidence=95.0)
    base.update(kw)
    return ExtractedDoc(**base)


def _classify(**kw) -> dict:
    return classify_document(_ext(**kw), COMPANY, {}, frozenset())


def test_complete_invoice_is_not_flagged():
    f = _classify()
    assert RECEIPT_REASON not in f["review_reasons"] and RECEIPT_REASON not in f["review_notes"]


def test_acknowledgement_receipt_without_tin_or_number_is_flagged_even_without_vat():
    f = _classify(document_title="ACKNOWLEDGEMENT RECEIPT", kind="receipt", doc_number="",
                  seller=Party(name="Mang Tomas Sari-Sari Store", address="Brgy. Sto. Niño"))
    assert RECEIPT_REASON in f["review_reasons"] and f["needs_review"] is True
    assert f["review_notes"][RECEIPT_REASON] == {"missing": ["seller TIN", "serial number"],
                                                "not_bir": "Acknowledgement receipt"}


def test_missing_address_alone_is_flagged():
    f = _classify(seller=Party(name="Golden Hardware Wholesale", tin="111222333"))
    assert f["review_notes"][RECEIPT_REASON] == {"missing": ["seller address"]}


def test_government_receipts_need_only_a_number():
    gov = Party(name="City Government of Marikina")
    assert receipt_problems("expenses", "buyer", "receipt", "OFFICIAL RECEIPT", gov.name, "", "", "7781904") is None
    assert receipt_problems("expenses", "buyer", "receipt", "OFFICIAL RECEIPT", "BIR", "", "", "") == {
        "missing": ["serial number"]}


def test_only_supplier_invoices_and_receipts_are_checked():
    args = ("ACKNOWLEDGEMENT RECEIPT", "", "", "", "")
    assert receipt_problems("sales", "seller", "invoice", *args) is None
    assert receipt_problems("payroll", "buyer", "payroll", *args) is None
    assert receipt_problems("expenses", "buyer", "bir2307", *args) is None
    assert receipt_problems("purchases", "buyer", "import", *args) is None


def _doc(**kw):
    base = dict(category="expenses", client_role="buyer", doc_type="receipt", document_title="OFFICIAL RECEIPT",
                seller_name="Park-N-Go Parking", seller_tin="", seller_address="Marikina", doc_number="PG-1",
                review_reasons=[], review_notes={}, needs_review=False, reviewed=False)
    base.update(kw)
    return SimpleNamespace(**base)


def test_sync_adds_then_clears_when_the_tin_is_typed_in():
    doc = _doc()
    assert sync_receipt_flag(doc) is True
    assert doc.review_reasons == [RECEIPT_REASON] and doc.needs_review is True
    assert doc.review_notes[RECEIPT_REASON] == {"missing": ["seller TIN"]}
    assert sync_receipt_flag(doc) is False   # nothing new
    doc.seller_tin = "444555666"
    assert sync_receipt_flag(doc) is True
    assert doc.review_reasons == [] and RECEIPT_REASON not in doc.review_notes and doc.needs_review is False


def test_sync_keeps_other_reasons_and_never_reflags_a_reviewed_document():
    doc = _doc(review_reasons=["low_confidence"], needs_review=True, seller_tin="444555666")
    assert sync_receipt_flag(doc) is False
    reviewed = _doc(reviewed=True)
    assert sync_receipt_flag(reviewed) is False and reviewed.review_reasons == []
