import random
from datetime import date
from decimal import Decimal

from app.services.accounting.books.chart import Chart, default_books, standard_chart
from app.services.accounting.compute.books import (
    BooksInput, FiledPayment, Line, ManualEntry, Payment, QuarterTaxes, depreciation_entries, post_all, tax_entries,
)
from app.services.accounting.compute.depreciation import Asset
from tests.aa_factories import company, expense, line, purchase, sale

D = Decimal
CHART = Chart(standard_chart("corporation"))
C = CHART.code


def books(**kw):
    values = dict(company=company(), chart=CHART, books_kept=frozenset(default_books(True)),
                  start=date(2026, 1, 1), through=date(2026, 9, 30))
    values.update(kw)
    return BooksInput(**values)


def amounts(entry):
    out: dict = {}
    for l in entry.lines:
        key = (l.account, "Dr" if l.debit else "Cr")
        out[key] = out.get(key, D("0")) + (l.debit or l.credit)
    return out


def test_vat_closing_with_payable():
    q = QuarterTaxes(2026, 3, date(2026, 9, 30), {"2550Q": {"37B": "1200.00", "60B": "700.00", "61B": "500.00",
                                                           "57B": "0.00", "16": "0.00"}})
    [e] = tax_entries(books(quarters=(q,)))
    assert e.id == "tax:2550Q:2026Q3:close" and e.book == "GJ" and e.date == date(2026, 9, 30)
    assert amounts(e) == {(C("output_vat"), "Dr"): D("1200.00"), (C("input_vat"), "Cr"): D("700.00"),
                          (C("vat_payable"), "Cr"): D("500.00")}


def test_vat_closing_with_negative_input_vat():
    q = QuarterTaxes(2026, 3, date(2026, 9, 30), {"2550Q": {"37B": "1000.00", "60B": "-200.00", "57B": "0.00", "16": "0.00"}})
    [e] = tax_entries(books(quarters=(q,)))
    assert amounts(e) == {(C("output_vat"), "Dr"): D("1000.00"), (C("input_vat"), "Dr"): D("200.00"),
                          (C("vat_payable"), "Cr"): D("1200.00")}


def test_vat_closing_with_excess_input_and_noncreditable_and_withheld():
    q = QuarterTaxes(2026, 3, date(2026, 9, 30), {"2550Q": {"37B": "1000.00", "60B": "1500.00", "61B": "-500.00",
                                                           "57B": "50.00", "16": "30.00"}})
    [e] = tax_entries(books(quarters=(q,)))
    assert amounts(e) == {(C("output_vat"), "Dr"): D("1000.00"), (C("input_vat"), "Cr"): D("1050.00"),
                          (C("input_vat_expense"), "Dr"): D("50.00"), (C("vat_payable"), "Dr"): D("30.00"),
                          (C("cwt"), "Cr"): D("30.00")}


def test_percentage_tax_withheld_is_applied_against_cwt_not_receivables():
    q = QuarterTaxes(2026, 1, date(2026, 3, 31), {"2551Q": {"14": "300.00", "15": "40.00"}})
    [e] = tax_entries(books(company=company(vat_registered=False), quarters=(q,)))
    assert amounts(e) == {(C("pt_expense"), "Dr"): D("300.00"), (C("pt_payable"), "Cr"): D("300.00"),
                          (C("pt_payable"), "Dr"): D("40.00"), (C("cwt"), "Cr"): D("40.00")}


def test_percentage_tax():
    q = QuarterTaxes(2026, 1, date(2026, 3, 31), {"2551Q": {"14": "300.00", "15": "0.00"}})
    [e] = tax_entries(books(company=company(vat_registered=False), quarters=(q,)))
    assert amounts(e) == {(C("pt_expense"), "Dr"): D("300.00"), (C("pt_payable"), "Cr"): D("300.00")}


def test_income_tax_accrues_the_increase_in_tax_due_and_applies_cwt():
    q1 = QuarterTaxes(2026, 1, date(2026, 3, 31), {"1702Q": {"14": "1000", "S4_5": "100"}})
    q2 = QuarterTaxes(2026, 2, date(2026, 6, 30), {"1702Q": {"14": "2500", "S4_5": "0"}})
    entries = {e.id: e for e in tax_entries(books(quarters=(q1, q2)))}
    assert amounts(entries["tax:ITQ:2026Q2:accrue"]) == {(C("income_tax"), "Dr"): D("1500.00"),
                                                          (C("it_payable"), "Cr"): D("1500.00")}
    assert amounts(entries["tax:ITQ:2026Q1:accrue"])[(C("cwt"), "Cr")] == D("100.00")


def test_income_tax_before_books_start_still_sets_the_baseline():
    q1 = QuarterTaxes(2026, 1, date(2026, 3, 31), {"1701Q": {"46": "800", "58": "0"}})
    q2 = QuarterTaxes(2026, 2, date(2026, 6, 30), {"1701Q": {"46": "1000", "58": "0"}})
    [e] = tax_entries(books(start=date(2026, 4, 1), quarters=(q1, q2)))
    assert amounts(e)[(C("income_tax"), "Dr")] == D("200.00")


def test_income_tax_uses_earlier_payments_but_not_prior_year_excess_as_baseline():
    q2 = QuarterTaxes(2026, 2, date(2026, 6, 30), {"1702Q": {"14": "3000", "S4_1": "700", "S4_2": "1000", "S4_4": "500", "S4_5": "0"}})
    [e] = tax_entries(books(quarters=(q2,)))
    assert amounts(e) == {(C("income_tax"), "Dr"): D("1500.00"), (C("it_payable"), "Cr"): D("1500.00")}


def test_filed_return_posts_its_payment_in_the_cash_disbursements_journal():
    paid = FiledPayment("0619E-M1", 2026, 3, date(2026, 8, 10), D("450"))
    [e] = tax_entries(books(filed=(paid,)))
    assert e.book == "CDJ" and e.date == date(2026, 8, 10)
    assert amounts(e) == {(C("ewt_payable"), "Dr"): D("450.00"), (C("bank"), "Cr"): D("450.00")}
    assert tax_entries(books(filed=(FiledPayment("2550Q", 2026, 3, date(2026, 10, 25), D("9")),))) == []


def test_monthly_depreciation():
    a = Asset("a1", "d1", "Laptop", "SI-7", D("60000"), date(2026, 7, 1), 60)
    entries = depreciation_entries(books(assets=(a,)))
    assert [e.date for e in entries] == [date(2026, 7, 31), date(2026, 8, 31), date(2026, 9, 30)]
    assert amounts(entries[0]) == {(C("depreciation"), "Dr"): D("1000.00"), (C("accum_dep"), "Cr"): D("1000.00")}


def test_depreciation_through_mid_month():
    a = Asset("a1", "d1", "Laptop", "SI-7", D("60000"), date(2026, 7, 1), 60)
    entries = depreciation_entries(books(assets=(a,), through=date(2026, 9, 15)))
    assert [e.date for e in entries] == [date(2026, 7, 31), date(2026, 8, 31)]


def test_post_all_orders_and_includes_typed_entries_in_window():
    opening = ManualEntry("o", "opening", "GJ", date(2026, 1, 1), "OB", "Opening balances",
                          (Line(C("cash"), debit=D("5000")), Line(C("capital"), credit=D("5000"))))
    later = ManualEntry("m", "manual", "GJ", date(2026, 12, 1), "", "", opening.lines)
    s = sale(gross="1120", vatable="1000", vat="120", doc_date=date(2026, 2, 1))
    entries, warnings = post_all(books(lines=(s,), manual=(opening, later)))
    assert [e.id for e in entries] == ["je:o", f"doc:{s.id}:sale"]
    assert entries[0].source == "opening" and warnings == []


def test_manual_entry_routes_unknown_book_to_gj():
    coll = ManualEntry("c", "manual", "CRJ", date(2026, 3, 1), "Adj", "Adjustment",
                       (Line(C("cash"), debit=D("100")), Line(C("ar"), credit=D("100"))))
    entries, _ = post_all(books(manual=(coll,), books_kept=frozenset(["GJ", "CDJ"])))
    assert entries[0].book == "GJ"


def test_random_documents_always_give_a_balanced_ledger():
    rng = random.Random(7)
    lines, pays, quarters = [], [], []
    for i in range(200):
        gross = D(rng.randint(-500, 50000)) + D(rng.randint(0, 99)) / 100
        vat = (gross * D("0.12") / D("1.12")).quantize(D("0.01"))
        kind = rng.choice(("sale", "buy", "exp", "pay", "2307"))
        on = date(2026, rng.randint(1, 9), rng.randint(1, 28))
        if kind == "sale":
            l = sale(gross=gross, vatable=gross - vat, vat=vat, withholding=rng.choice(("0", "15")), doc_date=on)
        elif kind == "buy":
            l = purchase(gross=gross, vat=vat, input_vat_valid=rng.choice((True, False)), doc_date=on)
        elif kind == "exp":
            l = expense(account=rng.choice(("rent", "utilities", "capital_goods")), gross=gross, doc_date=on)
        elif kind == "pay":
            l = line(category="payroll", account="salaries", gross=abs(gross), withholding="100", doc_date=on)
        else:
            l = line(category="2307", account="2307_received", client_role="seller", gross=gross, withholding="50",
                     doc_date=on)
        lines.append(l)
        if rng.random() < 0.5:
            pays.append(Payment(f"p{i}", l.id, date(2026, 9, 29), None, rng.choice(("cash", "bank")), ""))
    for q in range(1, 4):
        forms = {
            "2550Q": {
                "37B": str(D(rng.randint(-1000, 5000)) + D(rng.randint(0, 99)) / 100),
                "60B": str(D(rng.randint(-2000, 3000)) + D(rng.randint(0, 99)) / 100),
                "57B": str(max(D("0"), D(rng.randint(-500, 1000)) + D(rng.randint(0, 99)) / 100)),
                "16": str(max(D("0"), D(rng.randint(-100, 500)) + D(rng.randint(0, 99)) / 100)),
            },
            "1702Q": {
                "14": str(D(rng.randint(0, 3000)) + D(rng.randint(0, 99)) / 100),
                "S4_5": str(max(D("0"), D(rng.randint(-200, 800)) + D(rng.randint(0, 99)) / 100)),
            }
        }
        quarters.append(QuarterTaxes(2026, q, date(2026, q * 3, 30 if q != 3 else 30), forms))
    asset = Asset("a1", "SI-7", "Equipment", "SI-7", D("36000"), date(2026, 2, 1), 36)
    ewt = {l.id: D("10") for l in lines if l.category in ("purchases", "expenses")}
    entries, _ = post_all(books(lines=tuple(lines), payments=tuple(pays), quarters=tuple(quarters), assets=(asset,), ewt=ewt))
    assert sum((e.debits() for e in entries), D("0")) == sum((e.credits() for e in entries), D("0"))
