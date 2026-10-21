"""Reclassify: which postings behind an account can move, where to, and what moving them does (pure)."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

from app.services.accounting.books.chart import Chart, ChartAccount, standard_chart
from app.services.accounting.compute.books import Entry, Line
from app.services.accounting.compute.inputs import DocLine
from app.services.accounting.compute.reclassify import (
    apply_selection, candidates, check_target, document_main_account, preview,
)

D = Decimal


def chart(*extra: ChartAccount) -> Chart:
    return Chart(standard_chart("corporation") + list(extra))


def line(**kw) -> DocLine:
    values = dict(id="d1", category="expenses", account="rent", doc_type="invoice", client_role="buyer",
                  doc_date=date(2026, 10, 5), doc_number="RS-1", counterparty_tin="111222333",
                  counterparty_name="Sta. Elena Realty", counterparty_address="")
    values.update(kw)
    return DocLine(**values)


def entry(eid: str, on: date, *lines: Line, source="document") -> Entry:
    return Entry(eid, on, "PJ", "RS-1", "Sta. Elena", "", "Rent", source, lines)


def test_main_account_purchase_payroll_sale_capital():
    c = chart(ChartAccount("6021", "Rent - warehouse", "expense", parent_code="6020"))
    assert document_main_account(line(), c) == "6020"
    assert document_main_account(line(gl_account="6021"), c) == "6021"
    assert document_main_account(line(category="payroll", account="salaries"), c) == "6010"
    assert document_main_account(line(category="sales", client_role="seller", account="sales"), c) is None
    assert document_main_account(line(account="capital_goods"), c) is None
    assert document_main_account(line(category="2307"), c) is None


def _book():
    return [
        entry("doc:d1:buy", date(2026, 10, 5), Line("6020", debit=D("50000")), Line("2010", credit=D("50000"))),
        entry("pay:paid:d1", date(2026, 10, 9), Line("2010", debit=D("50000")), Line("1020", credit=D("50000")),
              source="payment"),
        entry("je:j1", date(2026, 10, 20), Line("6020", debit=D("1000")), Line("1010", credit=D("1000")),
              source="manual"),
        entry("tax:x", date(2026, 10, 31), Line("6020", debit=D("5")), Line("2150", credit=D("5")), source="tax"),
        entry("close:2026", date(2026, 12, 31), Line("3900", debit=D("51005")), Line("6020", credit=D("51005"))),
    ]


def test_candidates_list_document_and_je_and_other():
    rows = candidates(_book(), chart(), "6020", date(2026, 10, 1), date(2026, 12, 31),
                      docs={"d1": ("6020", "WC010")}, manual={"j1": "manual"}, last_closed=None)
    by = {r.key: r for r in rows}
    assert set(by) == {"document:d1", "journal_entry:j1", "tax:x"}
    assert by["document:d1"].movable and by["document:d1"].amount == D("50000.00")
    assert by["document:d1"].atc == "WC010"
    assert by["journal_entry:j1"].movable and by["journal_entry:j1"].kind == "journal_entry"
    assert not by["tax:x"].movable and by["tax:x"].why_not
    assert not any(r.closed for r in rows)


def test_candidates_already_moved_document_not_movable():
    rows = candidates(_book(), chart(), "6020", date(2026, 10, 1), date(2026, 10, 31),
                      docs={"d1": ("6900", "")}, manual={}, last_closed=None)
    doc = next(r for r in rows if r.key == "document:d1")
    assert not doc.movable and "6900" in doc.why_not
    je = next(r for r in rows if r.key == "journal_entry:j1")
    assert not je.movable  # unknown / deleted journal entry


def test_candidates_atc_filter():
    rows = candidates(_book(), chart(), "6020", date(2026, 10, 1), date(2026, 10, 31),
                      docs={"d1": ("6020", "WC010")}, manual={"j1": "manual"}, last_closed=None, atc="WI100")
    assert rows == []
    rows = candidates(_book(), chart(), "6020", date(2026, 10, 1), date(2026, 10, 31),
                      docs={"d1": ("6020", "WC010")}, manual={"j1": "manual"}, last_closed=None, atc="wc010")
    assert [r.key for r in rows] == ["document:d1"]


def test_candidates_skip_closing_and_reversals_but_follow_reposts():
    book = [
        entry("doc:d1:buy", date(2026, 9, 5), Line("6020", debit=D("100")), Line("2010", credit=D("100"))),
        entry("fix:doc:d1:buy:rev", date(2026, 10, 1), Line("2010", debit=D("100")), Line("6020", credit=D("100"))),
        entry("fix:doc:d2:buy:new", date(2026, 10, 1), Line("6020", debit=D("70")), Line("2010", credit=D("70"))),
    ]
    rows = candidates(book, chart(), "6020", date(2026, 9, 1), date(2026, 10, 31),
                      docs={"d1": ("6020", ""), "d2": ("6020", "")}, manual={}, last_closed=date(2026, 9, 30))
    assert [(r.key, r.closed) for r in rows] == [("document:d1", True), ("document:d2", False)]


def test_check_target_rules():
    c = chart(ChartAccount("6021", "Rent - warehouse", "expense", parent_code="6020"),
              ChartAccount("6022", "Old rent", "expense", parent_code="6020", active=False),
              ChartAccount("6061", "Gifts", "expense", parent_code="6060", locked=True))
    assert check_target(c, "6020", "6021", {"document"}) == ""
    assert "inactive" in check_target(c, "6020", "6022", {"document"})
    assert "locked" in check_target(c, "6020", "6061", {"document"})
    assert check_target(c, "6020", "6020", {"document"})
    assert "isn't in the chart" in check_target(c, "6020", "9999", {"document"})
    assert "Balance sheet" not in check_target(c, "6020", "2200", {"journal_entry"})
    assert "same statement" in check_target(c, "6020", "2200", {"journal_entry"})
    assert check_target(c, "1010", "1020", {"journal_entry"}) == ""  # cash on hand → bank, typed entry
    assert "cost or expense" in check_target(c, "4010", "4100", {"document"})
    assert check_target(c, "4010", "4100", {"journal_entry"}) == ""
    assert "posted by the books" in check_target(c, "6020", c.code("input_vat_expense"), {"document"})
    assert check_target(c, "6020", c.code("input_vat_expense"), {"journal_entry"}) == ""
    assert check_target(c, "6020", "", {"document"}) == ""  # ATC only


def test_preview_marks_closed_month_items():
    rows = candidates(_book(), chart(), "6020", date(2026, 10, 1), date(2026, 10, 31),
                      docs={"d1": ("6020", "WC010")}, manual={"j1": "manual"}, last_closed=date(2026, 10, 10))
    chosen, _ = apply_selection(rows, ["document:d1", "journal_entry:j1"])
    out = preview(chosen, chart(), "6900", "WC011", date(2026, 11, 1))
    by = {i["key"]: i for i in out["items"]}
    assert by["document:d1"]["posts_on"] == date(2026, 11, 1) and by["document:d1"]["to_atc"] == "WC011"
    assert by["journal_entry:j1"]["posts_on"] == date(2026, 10, 20) and by["journal_entry:j1"]["to_atc"] == ""
    assert by["journal_entry:j1"]["to"] == "6900" and by["document:d1"]["from"] == "6020"
    assert (out["count"], out["corrections"], out["total"]) == (2, 1, D("51000.00"))


def test_apply_selection_is_intersection():
    rows = candidates(_book(), chart(), "6020", date(2026, 10, 1), date(2026, 10, 31),
                      docs={"d1": ("6020", "")}, manual={"j1": "manual"}, last_closed=None)
    chosen, skipped = apply_selection(rows, ["document:d1", "document:other-firm", "tax:x", "document:d1"])
    assert [c.key for c in chosen] == ["document:d1"]
    assert skipped == ["document:other-firm", "tax:x"]


def test_atc_only_change_keeps_account():
    rows = candidates(_book(), chart(), "6020", date(2026, 10, 1), date(2026, 10, 31),
                      docs={"d1": ("6020", "WC010")}, manual={}, last_closed=None)
    chosen, _ = apply_selection(rows, ["document:d1"])
    item = preview(chosen, chart(), "", "WC011", None)["items"][0]
    assert (item["from"], item["to"], item["from_atc"], item["to_atc"]) == ("6020", "6020", "WC010", "WC011")
    assert replace(chosen[0], atc="") != chosen[0]


def _doc(**kw):
    from types import SimpleNamespace as NS

    values = dict(category="expenses", gl_account_code="", ewt_atc="", review_reasons=[], needs_review=False)
    values.update(kw)
    return NS(**values)


def test_move_document_out_of_a_locked_account_clears_the_flag():
    from app.services.accounting.compute.reclassify import move_document

    doc = _doc(review_reasons=["account_locked"], needs_review=True)
    move_document(doc, "6900", "")
    assert doc.gl_account_code == "6900" and doc.review_reasons == [] and doc.needs_review is False
    kept = _doc(review_reasons=["account_locked", "ewt_expected"], needs_review=True)
    move_document(kept, "6900", "WC011")
    assert kept.review_reasons == ["ewt_expected"] and kept.needs_review is True and kept.ewt_atc == "WC011"
    atc_only = _doc(review_reasons=["account_locked"], needs_review=True)
    move_document(atc_only, "", "WC011")   # still on the locked account
    assert atc_only.review_reasons == ["account_locked"] and atc_only.gl_account_code == ""


def test_move_document_atc_only_on_purchases_and_expenses():
    from app.services.accounting.compute.reclassify import move_document

    payroll = _doc(category="payroll")
    move_document(payroll, "6011", "WC011")
    assert (payroll.gl_account_code, payroll.ewt_atc) == ("6011", "")


def test_move_lines_rewrites_only_the_source_account():
    from app.services.accounting.compute.reclassify import move_lines

    lines = [{"account_code": "6020", "debit": "10"}, {"account_code": "1010", "credit": "10"}]
    assert move_lines(lines, "6020", "6900") == [{"account_code": "6900", "debit": "10"},
                                                  {"account_code": "1010", "credit": "10"}]


def test_preview_shows_atc_only_where_apply_sets_it():
    from app.services.accounting.compute.reclassify import atc_only_selection

    book = _book() + [entry("doc:p1:payroll", date(2026, 10, 15), Line("6020", debit=D("900")),
                            Line("2110", credit=D("900")))]
    rows = candidates(book, chart(), "6020", date(2026, 10, 1), date(2026, 10, 31),
                      docs={"d1": ("6020", "WC010"), "p1": ("6020", "")}, manual={"j1": "manual"}, last_closed=None)
    chosen, _ = apply_selection(rows, ["document:d1", "document:p1", "journal_entry:j1"])
    atc_keys = {"document:d1"}
    out = preview(chosen, chart(), "6900", "WC011", None, atc_keys)
    by = {i["key"]: i for i in out["items"]}
    assert by["document:d1"]["to_atc"] == "WC011" and by["document:p1"]["to_atc"] == ""
    kept, skipped = atc_only_selection(chosen, atc_keys)
    assert [c.key for c in kept] == ["document:d1"] and skipped == ["document:p1", "journal_entry:j1"]


def test_writeoff_ar_lines_cannot_move():
    from app.services.accounting.compute.reclassify import WRITEOFF

    book = [entry("je:w1", date(2026, 10, 20), Line("6140", debit=D("100")), Line("1100", credit=D("100")),
                  source="manual")]
    rows = candidates(book, chart(), "1100", date(2026, 10, 1), date(2026, 10, 31), docs={},
                      manual={"w1": WRITEOFF}, last_closed=None)
    assert len(rows) == 1 and not rows[0].movable and "write-off" in rows[0].why_not
