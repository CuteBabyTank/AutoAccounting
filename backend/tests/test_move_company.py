from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.services.accounting.classify import CompanyProfile
from app.services.accounting.move_company import MoveFacts, extracted_from_document, move_problem, resorted_fields

SELLER = CompanyProfile("010234567", "Bayanihan Hardware Trading Corp.", (), True, 12)
BUYER = CompanyProfile("201345678", "Mabuhay Builders Inc.", (), True, 12)


def _sales_invoice(**over):
    fields = dict(
        page_start=1, page_end=1, document_title="SALES INVOICE", doc_type="invoice", doc_number="0005",
        doc_date=date(2026, 10, 3), seller_name="BAYANIHAN HARDWARE TRADING CORP.", seller_tin="010234567", seller_branch="000",
        seller_address="123 Rizal Ave., Marikina City", seller_vat_registered=True,
        buyer_name="MABUHAY BUILDERS INC.", buyer_tin="201345678", buyer_branch="", buyer_address="45 Sumulong Hwy., Antipolo",
        gross_amount=Decimal("118004.32"), vatable_amount=Decimal("105361.00"), vat_amount=Decimal("12643.32"),
        exempt_amount=Decimal("0"), zero_rated_amount=Decimal("0"), withholding_amount=Decimal("0"), confidence=95.0,
        raw={"kind": "invoice", "nature": "goods_for_resale", "payment_terms": "credit",
             "seller": {"name": "Bayanihan", "tin": "010-234-567-000"}, "buyer": {"name": "Mabuhay"}},
    )
    fields.update(over)
    return SimpleNamespace(**fields)


def test_a_sale_moved_to_the_buyer_becomes_a_purchase():
    out = resorted_fields(_sales_invoice(), BUYER, {}, frozenset({SELLER.tin}))
    assert out["client_role"] == "buyer"
    assert out["category"] == "purchases"
    assert (out["period_year"], out["period_quarter"]) == (2026, 4)
    assert out["reviewed"] is False and out["settles_document_id"] is None and out["gl_account_code"] == ""


def test_hand_edits_survive_the_move():
    ext = extracted_from_document(_sales_invoice(doc_number="0005-A", gross_amount=Decimal("1.00")))
    assert ext.doc_number == "0005-A" and ext.gross_amount == Decimal("1.00")
    assert ext.nature == "goods_for_resale" and ext.payment_terms == "credit"  # what Gemini read is kept
    assert ext.seller.printed_branch == "000"


def test_document_with_nothing_read_still_moves():
    blank = _sales_invoice(raw=None, doc_type="other", seller_tin="", buyer_tin="", seller_name="", buyer_name="",
                           gross_amount=Decimal("0"), doc_date=None)
    out = resorted_fields(blank, BUYER, {}, frozenset())
    assert out["needs_review"] and out["period_year"] is None


def test_fiscal_year_of_the_new_company_sets_the_quarter():
    june_ye = CompanyProfile(BUYER.tin, BUYER.registered_name, (), True, 6)
    out = resorted_fields(_sales_invoice(), june_ye, {}, frozenset())
    assert (out["period_year"], out["period_quarter"]) == (2027, 2)


def test_move_problems():
    assert move_problem(MoveFacts()) is None
    for facts in (MoveFacts(is_statement=True), MoveFacts(has_asset=True), MoveFacts(confirmed_bank_match=True),
                  MoveFacts(written_off=True), MoveFacts(is_2307_for_a_sale=True)):
        assert move_problem(facts)
