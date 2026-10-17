"""Work board: filings a company owes in a window, their status, labels and filters (pure)."""

from dataclasses import replace
from datetime import date

from app.services.accounting.compute.due_dates import alphalist_due_date
from app.services.accounting.compute.inputs import CompanyFacts
from app.services.accounting.compute.work import (
    Obligation, derive_status, days_left, filter_cards, form_label, is_overdue, obligations, period_text,
    skip_obligation,
)

CORP = CompanyFacts("Bayanihan Hardware", "123456789", "00000", "040", "Marikina", "1800", "corporation", True,
                    "graduated", "itemized", "trading", 12, is_withholding_agent=True, has_employees=True)


def keys(obs):
    return {(o.form, o.year, o.quarter, o.due) for o in obs}


def test_alphalist_due_moves_off_the_weekend():
    assert alphalist_due_date(2026) == date(2027, 2, 1)   # Jan 31 2027 is a Sunday
    assert alphalist_due_date(2025) == date(2026, 2, 2)   # Jan 31 2026 is a Saturday


def test_october_november_window_for_a_vat_agent_with_employees():
    obs = obligations(CORP, date(2026, 10, 1), date(2026, 11, 30), set(), set())
    got = keys(obs)
    assert ("2550Q", 2026, 3, date(2026, 10, 26)) in got
    assert ("1601EQ", 2026, 3, date(2026, 11, 2)) in got
    assert ("1601C-M3", 2026, 3, date(2026, 10, 12)) in got
    assert ("0619E-M1", 2026, 4, date(2026, 11, 10)) in got
    assert ("1601C-M1", 2026, 4, date(2026, 11, 10)) in got
    assert not any(f == "1702Q" for f, *_ in got)          # due Dec 1, outside the window
    assert all(date(2026, 10, 1) <= o.due <= date(2026, 11, 30) for o in obs)


def test_annual_and_1604c_cards():
    obs = obligations(CORP, date(2027, 1, 1), date(2027, 4, 30), set(), set())
    got = keys(obs)
    assert ("1604C", 2026, 0, date(2027, 2, 1)) in got
    assert ("1702RT", 2026, 0, date(2027, 4, 15)) in got
    no_staff = replace(CORP, has_employees=False)
    assert not any(o.form == "1604C" for o in obligations(no_staff, date(2027, 1, 1), date(2027, 4, 30), set(), set()))
    # employee rows for the year bring the 1604-C back
    assert any(o.form == "1604C" for o in obligations(no_staff, date(2027, 1, 1), date(2027, 4, 30), set(), {2026}))


def test_payroll_documents_add_1601c():
    no_staff = replace(CORP, has_employees=False, is_withholding_agent=False)
    window = (date(2026, 10, 1), date(2026, 10, 31))
    assert not any(o.form.startswith("1601C") for o in obligations(no_staff, *window, set(), set()))
    assert any(o.form == "1601C-M3" for o in obligations(no_staff, *window, {(2026, 3)}, set()))


def test_fiscal_june_obligations():
    june = replace(CORP, fiscal_year_end_month=6)
    obs = obligations(june, date(2026, 10, 1), date(2026, 10, 31), set(), set())
    assert ("1702RT", 2026, 0, date(2026, 10, 15)) in keys(obs)
    may = replace(CORP, fiscal_year_end_month=5)   # withholding returns need calendar-aligned quarters
    assert not any(o.form.startswith(("0619E", "1601EQ")) for o in
                   obligations(may, date(2026, 1, 1), date(2026, 12, 31), set(), set()))


def test_individual_8_percent_files_1701q_and_no_percentage_tax():
    ind = replace(CORP, taxpayer_type="individual", vat_registered=False, income_tax_option="eight_percent",
                  is_withholding_agent=False, has_employees=False)
    forms = {o.form for o in obligations(ind, date(2026, 1, 1), date(2026, 12, 31), set(), set())}
    assert "1701Q" in forms and "2551Q" not in forms and "1701A" in forms


def test_derive_status():
    assert derive_status(filed=False, generated=False, documents=0, open_reviews=0) == "no_docs"
    assert derive_status(filed=False, generated=False, documents=3, open_reviews=0) == "docs_in"
    assert derive_status(filed=False, generated=False, documents=3, open_reviews=1) == "needs_review"
    assert derive_status(filed=False, generated=True, documents=3, open_reviews=1) == "generated"
    assert derive_status(filed=True, generated=False, documents=0, open_reviews=0) == "filed"
    assert derive_status(filed=False, generated=False, documents=0, open_reviews=0, override="docs_in") == "docs_in"
    assert derive_status(filed=False, generated=True, documents=0, open_reviews=0, override="bogus") == "generated"


def test_filed_beats_override():
    assert derive_status(filed=True, generated=True, documents=1, open_reviews=0, override="needs_review") == "filed"


def test_overdue_and_days_left():
    today = date(2026, 10, 27)
    assert is_overdue("generated", date(2026, 10, 26), today)
    assert not is_overdue("filed", date(2026, 10, 26), today)
    assert not is_overdue("no_docs", today, today)
    assert days_left(date(2026, 11, 10), today) == 14


def test_labels():
    assert form_label("0619E-M2") == "0619-E" and form_label("1601C-M1") == "1601-C"
    assert form_label("2550Q") == "2550-Q" and form_label("1702RT") == "1702-RT" and form_label("1604C") == "1604-C"
    assert form_label("1701A") == "1701-A" and form_label("1601EQ") == "1601-EQ"
    assert period_text(Obligation("0619E-M1", 2026, 4, date(2026, 11, 10)), 12) == "Oct 2026"
    assert period_text(Obligation("1601C-M3", 2026, 3, date(2026, 10, 12)), 12) == "Sep 2026"
    assert period_text(Obligation("2550Q", 2026, 3, date(2026, 10, 26)), 12) == "Q3 2026"
    assert period_text(Obligation("1702RT", 2026, 0, date(2027, 4, 15)), 12) == "FY 2026"
    assert period_text(Obligation("1702RT", 2026, 0, date(2026, 10, 15)), 6) == "FY Jun 2026"
    assert period_text(Obligation("1604C", 2026, 0, date(2027, 2, 1)), 12) == "CY 2026"


def test_old_empty_periods_skipped():
    added = date(2026, 10, 5)
    q2 = Obligation("2550Q", 2026, 2, date(2026, 7, 27))
    assert skip_obligation(q2, added, has_data=False)
    assert not skip_obligation(q2, added, has_data=True)
    q3 = Obligation("2550Q", 2026, 3, date(2026, 10, 26))   # still due after the client joined: the firm files it
    assert not skip_obligation(q3, added, has_data=False)
    q4 = Obligation("0619E-M1", 2026, 4, date(2026, 11, 10))
    assert not skip_obligation(q4, added, has_data=False)
    annual = Obligation("1702RT", 2026, 0, date(2027, 4, 15))  # year still running when added
    assert not skip_obligation(annual, added, has_data=False)


def test_filter_cards():
    cards = [
        {"company_id": "a", "status": "filed", "assignee_id": None},
        {"company_id": "b", "status": "docs_in", "assignee_id": "u1"},
        {"company_id": "a", "status": "docs_in", "assignee_id": "u2"},
    ]
    assert len(filter_cards(cards, company_id="a")) == 2
    assert len(filter_cards(cards, status="docs_in")) == 2
    assert filter_cards(cards, assignee="unassigned") == [cards[0]]
    assert filter_cards(cards, assignee="u1", status="docs_in") == [cards[1]]
    assert filter_cards(cards, status="open") == cards[1:]   # "open" = anything not filed
