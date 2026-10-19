"""Review rules from the Q4 2026 test pack (Bayanihan Hardware Trading Corp.)."""

from datetime import date
from decimal import Decimal

from app.services.accounting.classify import (
    REVIEW_REASONS,
    SOFT_REASONS,
    CompanyProfile,
    classify_document,
    needs_review_for,
)
from app.services.accounting.extraction import ExtractedDoc, Party

BAYANIHAN = CompanyProfile("009876543", "Bayanihan Hardware Trading Corp.", (), True, 12,
                           is_withholding_agent=True, owner_names=("Ramon P. Bayani",))
CLIENT = Party(name="Bayanihan Hardware Trading Corp.", tin="009876543")


def _ext(**kw) -> ExtractedDoc:
    base = dict(
        document_title="SALES INVOICE", kind="invoice", doc_number="1", doc_date=date(2026, 11, 3),
        seller=Party(name="Luzon Paint Supply", tin="111222333"), buyer=CLIENT, seller_vat_registered=True,
        gross_amount=Decimal("11200.00"), vatable_amount=Decimal("10000.00"), vat_amount=Decimal("1200.00"),
        nature="goods_for_resale", expense_account="purchases", confidence=95.0,
    )
    base.update(kw)
    return ExtractedDoc(**base)


def _classify(ext, company=BAYANIHAN):
    return classify_document(ext, company, {}, frozenset())


def test_new_reasons_are_known():
    for reason in ("tendered_less_than_total", "ewt_expected", "payment_source_unknown", "payment_unverified",
                   "duplicate_invoice_number", "personal_purchase"):
        assert reason in REVIEW_REASONS


def test_soft_reason_does_not_need_review():
    assert SOFT_REASONS == frozenset({"payment_unverified"})
    assert needs_review_for(["payment_unverified"]) is False
    assert needs_review_for(["payment_unverified", "low_confidence"]) is True
    assert needs_review_for([]) is False


def test_old_raw_without_new_fields_has_no_new_reasons():
    f = _classify(_ext())
    assert f["review_reasons"] == [] and f["review_notes"] == {} and f["excluded"] is False


def test_tendered_less_than_total_flags_and_keeps_the_total():
    # p20 Tindahan 0048029: cash tendered below the total, negative change
    receipt = _ext(document_title="SALES INVOICE", seller=Party(name="Tindahan ni Aling Nena", tin="222333444"),
                   doc_number="0048029", gross_amount=Decimal("560.00"), vatable_amount=Decimal("500.00"),
                   vat_amount=Decimal("60.00"), cash_tendered=Decimal("500.00"), change_amount=Decimal("-60.00"),
                   nature="other", expense_account="office_supplies")
    f = _classify(receipt)
    assert "tendered_less_than_total" in f["review_reasons"] and f["needs_review"] is True
    assert f["gross_amount"] == Decimal("560.00")
    assert f["review_notes"]["tendered_less_than_total"] == {"tendered": "500.00", "total": "560.00", "change": "-60.00"}
    only_change = _classify(_ext(change_amount=Decimal("-5.00")))
    assert "tendered_less_than_total" in only_change["review_reasons"]
    enough = _classify(_ext(cash_tendered=Decimal("12000.00"), change_amount=Decimal("800.00")))
    assert "tendered_less_than_total" not in enough["review_reasons"]


def test_ewt_expected_on_professional_fees_without_withholding():
    # p11 Reyes Santos RS-1048: professional fees, VAT-registered individual practitioner, no EWT shown
    bill = _ext(seller=Party(name="Reyes Santos Law Office", tin="333444555"), doc_number="RS-1048",
                gross_amount=Decimal("33600.00"), vatable_amount=Decimal("30000.00"), vat_amount=Decimal("3600.00"),
                nature="services", expense_account="professional_fees")
    f = _classify(bill)
    assert "ewt_expected" in f["review_reasons"]
    assert f["review_notes"]["ewt_expected"] == {"atc": "WI011", "rate": "10", "base": "30000.00", "amount": "3000.00"}
    withheld = _classify(_ext(**{**bill.__dict__, "withholding_amount": Decimal("3000.00")}))
    assert "ewt_expected" not in withheld["review_reasons"]
    not_agent = CompanyProfile(CLIENT.tin, CLIENT.name, (), True, 12)
    assert "ewt_expected" not in _classify(bill, not_agent)["review_reasons"]


def test_ewt_expected_on_corporate_rent():
    rent = _ext(seller=Party(name="Sta. Elena Realty Corp.", tin="444555666"), gross_amount=Decimal("33600.00"),
                vatable_amount=Decimal("30000.00"), vat_amount=Decimal("3600.00"), nature="services",
                expense_account="rent")
    f = _classify(rent)
    assert f["review_notes"]["ewt_expected"] == {"atc": "WC100", "rate": "5", "base": "30000.00", "amount": "1500.00"}


def test_payment_source_unknown_on_released_payroll():
    # p43: 13th month pay ₱120,000 marked released on 12/15, nothing shows where the cash came from
    payroll = _ext(kind="payroll", document_title="13TH MONTH PAY REGISTER", seller=Party(), nature="payroll",
                   expense_account="salaries", gross_amount=Decimal("120000.00"), vatable_amount=Decimal("0"),
                   vat_amount=Decimal("0"), doc_date=date(2026, 12, 15), marked_paid=True)
    f = _classify(payroll)
    assert f["category"] == "payroll" and "payment_source_unknown" in f["review_reasons"] and f["needs_review"]
    unpaid = _classify(_ext(**{**payroll.__dict__, "marked_paid": False}))
    assert "payment_source_unknown" not in unpaid["review_reasons"]


def test_payment_unverified_is_soft():
    # Pacific Steel on credit terms: no payment evidence yet, shown but never blocking
    f = _classify(_ext(seller=Party(name="Pacific Steel Corp.", tin="555666777"), payment_terms="credit"))
    assert f["review_reasons"] == ["payment_unverified"] and f["needs_review"] is False
    cash = _classify(_ext(payment_terms="cash"))
    assert "payment_unverified" not in cash["review_reasons"]


def test_golden_hardware_vat_mismatch_keeps_input_vat_at_twelve_percent():
    # p16 Golden Hardware: VAT ₱2,600 printed on ₱20,000 (should be ₱2,400)
    golden = _ext(seller=Party(name="Golden Hardware Depot", tin="666777888"), gross_amount=Decimal("22600.00"),
                  vatable_amount=Decimal("20000.00"), vat_amount=Decimal("2600.00"))
    f = _classify(golden)
    assert "vat_math_mismatch" in f["review_reasons"]
    assert f["input_vat_valid"] is True and f["vat_treatment"] == "vatable"
    assert f["review_notes"]["vat_math_mismatch"] == {"expected": "2400.00", "difference": "200.00"}
    receipt = _classify(_ext(**{**golden.__dict__, "document_title": "OFFICIAL RECEIPT"}))
    assert receipt["input_vat_valid"] is False   # other input-VAT issues still disallow it


def test_personal_purchase_in_owners_name_is_excluded():
    # p38: purchase receipt made out to the owner personally
    personal = _ext(buyer=Party(name="RAMON P. BAYANI"), seller=Party(name="SM Appliance Center", tin="777888999"),
                    nature="other", expense_account="other")
    f = _classify(personal)
    assert {"not_addressed_to_client", "personal_purchase"} <= set(f["review_reasons"])
    assert f["excluded"] is True and f["needs_review"] is True
    blank = _classify(_ext(buyer=Party(), nature="other", expense_account="other"))  # p21: buyer block blank
    assert "personal_purchase" not in blank["review_reasons"] and blank["excluded"] is False


# --- VAT difference posting (p16 Golden Hardware) -------------------------------------------------

def _golden_line(vat="2600"):
    from tests.aa_factories import purchase
    return purchase(gross=str(20000 + int(vat)), vatable="20000", vat=vat, input_vat_valid=True,
                    counterparty_name="Golden Hardware Depot")


def test_golden_purchase_posts_the_excess_vat_to_vat_difference():
    from app.services.accounting.books.chart import Chart, default_books, standard_chart
    from app.services.accounting.compute.books import BooksInput, document_entries
    from tests.aa_factories import company

    chart = Chart(standard_chart("corporation"))
    assert chart.get(chart.code("vat_difference")).name == "VAT difference - for review"
    inp = BooksInput(company=company(), chart=chart, books_kept=frozenset(default_books(True)),
                     start=date(2026, 1, 1), through=date(2026, 12, 31))
    [e] = document_entries(_golden_line(), inp)
    got = {(l.account, "Dr" if l.debit else "Cr"): l.debit or l.credit for l in e.lines}
    assert got == {(chart.code("doc:purchases"), "Dr"): Decimal("20000.00"),
                   (chart.code("input_vat"), "Dr"): Decimal("2400.00"),
                   (chart.code("vat_difference"), "Dr"): Decimal("200.00"),
                   (chart.code("ap"), "Cr"): Decimal("22600.00")}


def test_golden_purchase_claims_twelve_percent_on_the_2550q():
    from app.services.accounting.compute.inputs import PeriodInputs
    from app.services.accounting.compute.vat import compute_2550q

    i = compute_2550q([_golden_line()], PeriodInputs(), Decimal("0")).items
    assert i["44A"] == Decimal("20000.00") and i["44B"] == Decimal("2400.00")


def test_vat_below_twelve_percent_claims_printed_vat():
    from app.services.accounting.compute.cogs import claimed_input_vat, vat_difference

    low = _golden_line(vat="2200")
    assert claimed_input_vat(low, True) == Decimal("2200.00") and vat_difference(low, True) == Decimal("0.00")
    assert claimed_input_vat(_golden_line(vat="2400"), True) == Decimal("2400.00")
    assert claimed_input_vat(_golden_line(), False) == Decimal("0.00")


def test_charts_seeded_before_vat_difference_get_it():
    from app.services.accounting.books.chart import missing_standard, standard_chart

    old = [a for a in standard_chart("corporation") if a.system_key != "vat_difference"]
    assert [a.code for a in missing_standard(old, "corporation")] == ["1310"]


# --- Duplicates: Luzon Paint SI 5838 scanned twice; per-supplier invoice-number reuse ----------------

def _dup(number="5838", day=date(2026, 10, 7), gross="56000.00", category="purchases", cleared=()):
    import uuid

    from app.services.accounting.duplicates import DupDoc
    return DupDoc(id=uuid.uuid4(), role="buyer", counterparty="111222333", doc_number=number, doc_date=day,
                  gross=Decimal(gross), not_duplicate_of=frozenset(cleared), category=category)


def test_luzon_paint_5838_scanned_twice_is_a_duplicate():
    from app.services.accounting.classify import mark_duplicates
    from app.services.accounting.duplicates import SAME_NUMBER, Pair, duplicate_pairs

    p6, p7 = _dup(), _dup()
    assert duplicate_pairs([p6, p7]) == [Pair(p6.id, p7.id, SAME_NUMBER)]
    luzon = _ext(doc_number="5838", gross_amount=Decimal("56000.00"), vatable_amount=Decimal("50000.00"),
                 vat_amount=Decimal("6000.00"))
    rows = [_classify(luzon), _classify(luzon)]
    mark_duplicates(rows, set())
    assert "possible_duplicate" not in rows[0]["review_reasons"]
    assert "possible_duplicate" in rows[1]["review_reasons"] and rows[1]["needs_review"] is True


def test_supplier_reusing_an_invoice_number_is_its_own_reason():
    from app.services.accounting.duplicates import NUMBER_REUSED, Pair, duplicate_pairs

    first, again = _dup(), _dup(day=date(2026, 12, 2), gross="12000.00")
    assert duplicate_pairs([first, again]) == [Pair(first.id, again.id, NUMBER_REUSED)]
    cleared = _dup(day=date(2026, 12, 2), cleared=(str(first.id),))
    assert duplicate_pairs([first, cleared]) == []


def test_number_reuse_ignores_support_papers():
    from app.services.accounting.duplicates import duplicate_pairs

    assert duplicate_pairs([_dup(category="support"), _dup(category="support", day=date(2026, 11, 7))]) == []


def test_sync_flags_uses_the_number_reuse_reason():
    import uuid
    from types import SimpleNamespace

    from app.services.accounting.duplicates import NUMBER_FLAG, NUMBER_REUSED, Pair, sync_flags

    def doc(reasons=()):
        return SimpleNamespace(id=uuid.uuid4(), review_reasons=list(reasons), needs_review=bool(reasons),
                               reviewed=False)
    first, again = doc(), doc(["possible_duplicate"])   # the upload's per-file check flagged it first
    sync_flags([Pair(first.id, again.id, NUMBER_REUSED)], {first.id: first, again.id: again})
    assert again.review_reasons == [NUMBER_FLAG] and again.needs_review is True
    sync_flags([], {first.id: first, again.id: again})
    assert again.review_reasons == [] and again.needs_review is False


# --- Payment evidence flags (cleared by evidence; workstream 03 adds bank lines) ---------------------

def _doc(category="payroll", raw=None, reviewed=False, paid_on=None, settles=None, reasons=None):
    import uuid
    from types import SimpleNamespace

    raw = {"marked_paid": True} if raw is None else raw
    return SimpleNamespace(id=uuid.uuid4(), category=category, client_role="buyer", raw=raw, reviewed=reviewed,
                           paid_on=paid_on, settles_document_id=settles, deleted_at=None, excluded=False,
                           review_reasons=list(reasons or []), needs_review=bool(reasons))


def test_payment_reasons():
    from app.services.accounting.review_rules import payment_reasons

    assert payment_reasons("payroll", "buyer", {"marked_paid": True}) == ["payment_source_unknown"]
    assert payment_reasons("purchases", "buyer", {"payment_terms": "Credit"}) == ["payment_unverified"]
    assert payment_reasons("sales", "seller", {"payment_terms": "credit"}) == []
    assert payment_reasons("payroll", "buyer", None) == []


def test_payment_flags_follow_evidence():
    from app.services.accounting.review_rules import sync_payment_flags

    payroll = _doc(reasons=["payment_source_unknown"])
    bill = _doc(category="purchases", raw={"payment_terms": "credit"}, reasons=["payment_unverified"])
    receipt = _doc(category="support", raw={}, settles=bill.id)
    sync_payment_flags([payroll, bill, receipt], paid_ids={str(payroll.id)})   # e.g. a matched bank line
    assert payroll.review_reasons == [] and payroll.needs_review is False
    assert bill.review_reasons == []
    sync_payment_flags([payroll, bill])                                         # evidence gone: back again
    assert payroll.review_reasons == ["payment_source_unknown"] and payroll.needs_review is True
    assert bill.review_reasons == ["payment_unverified"] and bill.needs_review is False
    paid = _doc(paid_on=date(2026, 12, 15), reasons=["payment_source_unknown"])
    sync_payment_flags([paid])
    assert paid.review_reasons == []
    done = _doc(reviewed=True)
    sync_payment_flags([done])
    assert done.review_reasons == []          # never re-added to a reviewed document


def test_amount_received_net_of_withholding_is_not_short():
    # An OR printing "amount received" net of the EWT the payer withheld is fully paid, not short.
    net = _classify(_ext(gross_amount=Decimal("112000.00"), vatable_amount=Decimal("100000.00"),
                         vat_amount=Decimal("12000.00"), withholding_amount=Decimal("2000.00"),
                         cash_tendered=Decimal("110000.00")))
    assert "tendered_less_than_total" not in net["review_reasons"]
    short = _classify(_ext(gross_amount=Decimal("112000.00"), vatable_amount=Decimal("100000.00"),
                           vat_amount=Decimal("12000.00"), withholding_amount=Decimal("2000.00"),
                           cash_tendered=Decimal("100000.00")))
    assert "tendered_less_than_total" in short["review_reasons"]


def test_month_close_ignores_reviewed_documents():
    # A reviewed document keeps its reasons (and needs_review) for the record; it must not block the close.
    from datetime import date as d
    import uuid

    from app.services.accounting.books.closing import open_review_query

    sql = str(open_review_query(uuid.uuid4(), d(2026, 10, 1), d(2026, 10, 31)).compile())
    assert "aa_documents.reviewed IS false" in sql and "aa_documents.needs_review IS true" in sql
    assert "aa_documents.excluded IS false" in sql and "aa_documents.deleted_at IS NULL" in sql


def test_bulk_targets_skip_other_reasons():
    from types import SimpleNamespace as NS
    from datetime import datetime, timezone

    from app.services.accounting.review_rules import bulk_targets

    def doc(i, reasons, **kw):
        return NS(**dict(dict(id=i, needs_review=True, reviewed=False, excluded=False, deleted_at=None,
                              review_reasons=reasons), **kw))

    docs = [doc(1, ["ewt_expected"]), doc(2, ["ewt_expected", "low_confidence"]), doc(3, ["low_confidence"]),
            doc(4, ["ewt_expected"], reviewed=True), doc(5, ["ewt_expected"], excluded=True),
            doc(6, ["ewt_expected"], deleted_at=datetime.now(timezone.utc))]
    ok, skipped = bulk_targets(docs, "ewt_expected")
    assert [d.id for d in ok] == [1, 2]
    assert [(i, why) for i, why in skipped] == [
        (3, "doesn't carry this reason"), (4, "already resolved"), (5, "already resolved"), (6, "deleted")]


D = Decimal


def _legacy(**kw):
    from types import SimpleNamespace

    values = dict(category="purchases", client_role="buyer", vat_amount=D("1500.00"), vatable_amount=D("10000.00"),
                  input_vat_valid=False, vat_treatment="no_input_vat", review_reasons=["vat_math_mismatch"],
                  review_notes={})
    values.update(kw)
    return SimpleNamespace(**values)


def test_older_vat_mismatch_documents_claim_12_percent_unless_the_quarter_was_filed():
    from app.services.accounting.review_rules import apply_legacy_vat_fix, legacy_vat_fix

    doc = _legacy()
    assert legacy_vat_fix(doc, filed=False) == "claim"
    assert apply_legacy_vat_fix(doc, filed=False) is True
    assert doc.input_vat_valid is True and doc.vat_treatment == "vatable"
    assert doc.review_notes["vat_math_mismatch"] == {"expected": "1200.00", "difference": "300.00"}
    assert legacy_vat_fix(doc, filed=False) is None and apply_legacy_vat_fix(doc, filed=False) is False  # idempotent

    kept = _legacy()
    assert apply_legacy_vat_fix(kept, filed=True) is True        # flagged, not changed
    assert kept.input_vat_valid is False and kept.review_notes["vat_math_mismatch"]["legacy"] == "filed"
    assert apply_legacy_vat_fix(kept, filed=True) is False
    assert apply_legacy_vat_fix(kept, filed=False) is True and kept.input_vat_valid is True   # quarter unfiled later
    assert "legacy" not in kept.review_notes["vat_math_mismatch"]


def test_legacy_vat_fix_leaves_other_input_vat_problems_alone():
    from app.services.accounting.review_rules import legacy_vat_fix

    assert legacy_vat_fix(_legacy(review_reasons=["vat_math_mismatch", "not_an_invoice"]), filed=False) is None
    assert legacy_vat_fix(_legacy(review_reasons=["vat_math_mismatch", "seller_not_vat_registered"]), False) is None
    assert legacy_vat_fix(_legacy(review_reasons=["vat_math_mismatch", "not_addressed_to_client"]), False) is None
    assert legacy_vat_fix(_legacy(review_reasons=["low_confidence"]), filed=False) is None
    assert legacy_vat_fix(_legacy(input_vat_valid=None), filed=False) is None
    assert legacy_vat_fix(_legacy(client_role="seller", category="sales"), filed=False) is None
    assert legacy_vat_fix(_legacy(vat_amount=D("0")), filed=False) is None
    # a person's other reasons (e.g. low confidence) don't stop it
    assert legacy_vat_fix(_legacy(review_reasons=["vat_math_mismatch", "low_confidence"]), filed=False) == "claim"
