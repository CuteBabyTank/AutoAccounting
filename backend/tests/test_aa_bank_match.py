from datetime import date
from decimal import Decimal

from app.services.accounting.bank_match import (
    BankLineFact, Candidate, Rule, learn_rule, match_all, match_line, name_tokens, open_items,
)
from tests.aa_factories import expense, line, sale

D = Decimal


# Q4 pack documents that the December bank lines could pay (plus the traps: City permit ₱3,500, Park-N-Go ₱150,
# and the older Mabuhay invoice SI 0005).
RENT = expense(id="rent", account="rent", counterparty_name="Sta. Elena Realty Corp.", doc_number="2026-1524",
               doc_date=date(2026, 12, 1), gross="33600", vatable="30000", vat="3600")
PETRO = expense(id="petro", account="transportation", counterparty_name="Petro Bayan Gas Station",
                doc_number="PB-44437", doc_date=date(2026, 12, 4), gross="3500", vatable="3125", vat="375")
CITY = expense(id="city", account="taxes_licenses", counterparty_name="City Government of Marikina",
               doc_number="OR-7781904", doc_date=date(2026, 11, 3), gross="3500")
SI8 = sale(id="si8", counterparty_name="Mabuhay Builders Inc.", doc_number="0008", doc_date=date(2026, 12, 10),
           gross="131476.80", vatable="117390", vat="14086.80")
SI5 = sale(id="si5", counterparty_name="Mabuhay Builders Inc.", doc_number="0005", doc_date=date(2026, 10, 3),
           gross="117994.32", vatable="105351", vat="12643.32")
QUICKFIX = expense(id="quickfix", account="repairs", counterparty_name="QuickFix Aircon Services",
                   doc_number="OR-0659", doc_date=date(2026, 12, 18), gross="6720")
PAYROLL = line(id="payroll", category="payroll", account="salaries", counterparty_name="", doc_number="PR-2026-12",
               doc_date=date(2026, 12, 23), gross="120000", withholding="5294.70")
GOLDEN = expense(id="golden", account="purchases", category="purchases", counterparty_name="Golden Hardware Wholesale",
                 doc_number="8098", doc_date=date(2026, 12, 25), gross="22600", vatable="20000", vat="2600")
PARKNGO = expense(id="parkngo", account="transportation", counterparty_name="Park-N-Go Parking",
                  doc_number="PG-034728", doc_date=date(2026, 11, 2), gross="150")
DOCS = [RENT, PETRO, CITY, SI8, SI5, QUICKFIX, PAYROLL, GOLDEN, PARKNGO]
EWT = {"rent": D("1500.00")}
CONTRIBUTIONS = {"payroll": D("9300.00")}

LINES = [
    BankLineFact("l1", date(2026, 12, 2), D("-32100.00"), "Check #000818 - Sta. Elena Realty (Dec rent)", "000818"),
    BankLineFact("l2", date(2026, 12, 4), D("-3500.00"), "POS - Petro Bayan Gas Station"),
    BankLineFact("l3", date(2026, 12, 11), D("50000.00"), "Deposit - Mabuhay Builders (partial SI 0008)"),
    BankLineFact("l4", date(2026, 12, 15), D("38450.00"), "Cash deposit - store sales"),
    BankLineFact("l5", date(2026, 12, 18), D("-6720.00"), "Online transfer - QuickFix Aircon"),
    BankLineFact("l6", date(2026, 12, 23), D("-105405.30"), "Payroll credit - 4 employees"),
    BankLineFact("l7", date(2026, 12, 25), D("-22600.00"), "Check #000819 - Golden Hardware Wholesale", "000819"),
    BankLineFact("l8", date(2026, 12, 31), D("-150.00"), "Service charge"),
]


def candidates(docs=DOCS, paid=None):
    return open_items(docs, EWT, CONTRIBUTIONS, paid or {})


def test_open_items_are_what_the_counterparty_actually_pays():
    by_ref = {c.ref: c for c in candidates()}
    assert by_ref["rent"].amount == D("32100.00") and by_ref["rent"].direction == "out"
    assert by_ref["payroll"].amount == D("105405.30") and "payroll" in by_ref["payroll"].keywords
    assert by_ref["si8"].amount == D("131476.80") and by_ref["si8"].direction == "in"
    assert "parkngo" in by_ref
    assert "si8" not in {c.ref for c in candidates(paid={"si8": D("131476.80")})}
    assert {c.ref: c.amount for c in candidates(paid={"si8": D("50000")})}["si8"] == D("81476.80")


def test_q4_december_statement_auto_links_seven_of_eight():
    result = match_all(LINES, candidates())
    matched = {k: (m.kind, m.ref, m.amount) for k, m in result.items() if m.status == "matched"}
    assert matched == {
        "l1": ("document", "rent", D("32100.00")),
        "l2": ("document", "petro", D("3500.00")),
        "l3": ("document", "si8", D("50000.00")),
        "l4": ("posting", "", D("38450.00")),
        "l5": ("document", "quickfix", D("6720.00")),
        "l6": ("document", "payroll", D("105405.30")),
        "l7": ("document", "golden", D("22600.00")),
    }
    assert result["l4"].posting["key"] == "cash" and result["l4"].posting["kind"] == "transfer"
    charge = result["l8"]
    assert charge.status == "suggested" and charge.kind == "posting" and charge.posting["key"] == "bank_charges"
    assert charge.ref == ""  # the ₱150 parking bill is never linked …
    assert [c["ref"] for c in charge.candidates] == ["parkngo"]  # … only shown as an alternative


def test_fuel_pos_with_only_the_city_permit_is_ambiguous_never_linked():
    m = match_line(LINES[1], [c for c in candidates() if c.ref == "city"])
    assert m.status == "ambiguous" and m.reason == "bank_match_ambiguous" and m.ref == ""
    assert m.candidates[0]["ref"] == "city" and m.candidates[0]["strength"] == "conflict"


def test_amount_alone_never_links():
    bare = BankLineFact("x", date(2026, 12, 5), D("-3500.00"), "DEBIT MEMO")
    m = match_line(bare, [c for c in candidates() if c.ref == "petro"])
    assert m.status == "ambiguous" and m.ref == ""


def test_two_strong_candidates_are_ambiguous():
    twin = expense(id="petro2", counterparty_name="Petro Bayan Gas Station", doc_number="PB-44438",
                   doc_date=date(2026, 12, 3), gross="3500")
    m = match_line(LINES[1], candidates(DOCS + [twin]))
    assert m.status == "ambiguous" and {c["ref"] for c in m.candidates} >= {"petro", "petro2"}


def test_outside_the_date_window_is_not_a_candidate():
    late = BankLineFact("x", date(2027, 6, 1), D("-22600.00"), "Check #000819 - Golden Hardware Wholesale")
    assert match_line(late, candidates()).status == "unmatched"
    assert match_line(late, candidates()).reason == "bank_line_unmatched"


def test_rejected_candidate_is_not_relinked():
    result = match_all(LINES, candidates(), rejected={"l2": {"petro"}})
    assert result["l2"].status != "matched"
    assert "petro" not in {c["ref"] for c in result["l2"].candidates}


def test_open_amount_is_consumed_by_earlier_lines():
    again = BankLineFact("l7b", date(2026, 12, 26), D("-22600.00"), "Check #000819 - Golden Hardware Wholesale")
    result = match_all([LINES[6], again], candidates())
    assert result["l7"].status == "matched" and result["l7b"].status == "unmatched"


def test_learned_payee_rule_makes_a_bare_narration_strong():
    meralco = expense(id="meralco", account="utilities", counterparty_name="Metro Luzon Electric Company",
                      counterparty_tin="000111222", doc_number="EB-7781-2525", doc_date=date(2026, 11, 15),
                      gross="9464")
    ada = BankLineFact("m", date(2026, 11, 25), D("-9464.00"), "MLEC ADA DEBIT 4412889001")
    assert match_line(ada, candidates([meralco])).status == "ambiguous"
    rule = learn_rule(ada, "document", candidates([meralco])[0], "")
    assert rule == Rule("mlec ada", "out", "payee", "", "Metro Luzon Electric Company", "000111222")
    assert match_line(ada, candidates([meralco]), rules=[rule]).status == "matched"


def test_learned_posting_rule_suggests_its_account():
    line_ = BankLineFact("p", date(2026, 12, 31), D("-500.00"), "INSURANCE PREMIUM AUTO DEBIT")
    rule = learn_rule(line_, "posting", None, "6900")
    assert rule.kind == "posting" and rule.account_code == "6900" and rule.direction == "out"
    m = match_line(line_, [], rules=[rule])
    assert m.status == "suggested" and m.posting["account"] == "6900"


def test_interest_and_atm_withdrawal_suggestions():
    interest = match_line(BankLineFact("i", date(2026, 12, 31), D("12.40"), "Interest earned"), [])
    assert interest.status == "suggested" and interest.posting["key"] == "interest_income"
    atm = match_line(BankLineFact("a", date(2026, 12, 3), D("-5000.00"), "ATM withdrawal"), [])
    assert atm.status == "suggested" and atm.posting["key"] == "cash"


def test_cash_deposit_with_a_same_amount_sale_waits_for_a_person():
    cash_sale = sale(id="cs", counterparty_name="Walk-in", doc_number="0010", doc_date=date(2026, 12, 14),
                     gross="38450")
    m = match_line(LINES[3], candidates([cash_sale]))
    assert m.status == "suggested" and m.posting["key"] == "cash"


def test_name_tokens_drop_bank_and_corporate_words():
    assert name_tokens("POS - Petro Bayan Gas Station") == {"petro", "bayan"}
    assert name_tokens("Service charge") == set()
    assert name_tokens("City Government of Marikina") == {"marikina"}


def test_number_match_uses_doc_number_and_ignores_years():
    cand = Candidate("document", "x", date(2026, 12, 1), D("100.00"), "out", "Somebody Else", ("2026-1524",))
    hit = match_line(BankLineFact("n", date(2026, 12, 2), D("-100.00"), "BILLS PAYMENT REF 1524"), [cand])
    assert hit.status == "matched"
    year_only = match_line(BankLineFact("n", date(2026, 12, 2), D("-100.00"), "BILLS PAYMENT 12/02/2026"), [cand])
    assert year_only.status != "matched"
