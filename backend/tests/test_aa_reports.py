"""Live reports from the books (pure): P&L, Balance Sheet, comparisons, GL detail, adjusted TB, checks, drill-down."""

from datetime import date
from decimal import Decimal

from app.services.accounting.books.chart import Chart, ChartAccount, standard_chart
from app.services.accounting.compute.books import Entry, Line
from app.services.accounting.compute.reports import (
    adjusted_tb, adjusting_entries, balance_sheet, cash_balance, cash_flow, check_entries, check_manual, columns_for, entry_ref,
    gl_detail, kpis, postings, prior_window, profit_and_loss, shape, transaction_list, with_change,
)

D = Decimal
CHART = Chart(standard_chart("corporation") + [ChartAccount("6999", "Old account", "expense", active=False)])


def E(id, on, *lines, source="document", party=("", ""), book="GJ", ref="REF"):
    return Entry(id, on, book, ref, party[0], party[1], f"{id} particulars", source,
                 tuple(Line(a, D(dr), D(cr)) for a, dr, cr in lines))


ENTRIES = [
    E("je:open", date(2025, 1, 1), ("1010", "100000", "0"), ("3010", "0", "100000"), source="opening"),
    E("doc:s25:sale", date(2025, 6, 15), ("1010", "5000", "0"), ("4010", "0", "5000")),
    E("doc:s1:sale", date(2026, 10, 5), ("1100", "11200", "0"), ("4010", "0", "10000"), ("2100", "0", "1200"),
      party=("Kalayaan Builders", "123456789"), book="SJ", ref="0006"),
    E("doc:b1:buy", date(2026, 10, 20), ("5010", "4000", "0"), ("1300", "480", "0"), ("2010", "0", "4480"),
      party=("Luzon Paint", "987654321"), book="PJ", ref="5838"),
    E("doc:r1:buy", date(2026, 11, 10), ("6020", "2000", "0"), ("1010", "0", "2000"), party=("Sta. Elena", "")),
    E("dep:a1:2026-11", date(2026, 11, 30), ("6100", "500", "0"), ("1510", "0", "500"), source="depreciation"),
    E("je:adj1", date(2026, 12, 15), ("6020", "300", "0"), ("2010", "0", "300"), source="manual"),
    E("pay:rcpt:r9", date(2026, 12, 20), ("1020", "11200", "0"), ("1100", "0", "11200"), source="payment",
      party=("Kalayaan Builders", "123456789"), book="CRJ"),
    E("close:2026:pnl", date(2026, 12, 31), ("4010", "10000", "0"), ("3900", "0", "10000"), source="closing"),
]


def _row(report, key):
    return next(r for r in report["rows"] if r["key"] == key)


def test_columns_and_prior_windows():
    cols = columns_for(date(2026, 10, 1), date(2026, 12, 31), "month", 12)
    assert [(c.label, c.start, c.end) for c in cols] == [
        ("Oct 2026", date(2026, 10, 1), date(2026, 10, 31)), ("Nov 2026", date(2026, 11, 1), date(2026, 11, 30)),
        ("Dec 2026", date(2026, 12, 1), date(2026, 12, 31))]
    q = columns_for(date(2026, 1, 15), date(2026, 12, 31), "quarter", 6)
    assert [(c.label, c.start, c.end) for c in q] == [
        ("Q3 FY2026", date(2026, 1, 15), date(2026, 3, 31)), ("Q4 FY2026", date(2026, 4, 1), date(2026, 6, 30)),
        ("Q1 FY2027", date(2026, 7, 1), date(2026, 9, 30)), ("Q2 FY2027", date(2026, 10, 1), date(2026, 12, 31))]
    assert len(columns_for(date(2026, 10, 1), date(2026, 12, 31), "total", 12)) == 1
    assert prior_window(date(2026, 10, 1), date(2026, 12, 31), "period") == (date(2026, 7, 1), date(2026, 9, 30))
    assert prior_window(date(2026, 10, 1), date(2026, 12, 31), "year") == (date(2025, 10, 1), date(2025, 12, 31))
    assert prior_window(date(2026, 10, 5), date(2026, 10, 14), "period") == (date(2026, 9, 25), date(2026, 10, 4))
    assert prior_window(date(2028, 2, 1), date(2028, 2, 29), "year") == (date(2027, 2, 1), date(2027, 2, 28))


def test_pnl_by_month_and_total():
    cols = columns_for(date(2026, 10, 1), date(2026, 12, 31), "month", 12)
    report = profit_and_loss(ENTRIES, CHART, cols)
    assert _row(report, "net_sales")["values"] == [D("10000.00"), D("0.00"), D("0.00")]
    assert _row(report, "cos")["values"] == [D("4000.00"), D("0.00"), D("0.00")]
    assert _row(report, "net_income")["values"] == [D("6000.00"), D("-2500.00"), D("-300.00")]
    total = profit_and_loss(ENTRIES, CHART, columns_for(date(2026, 10, 1), date(2026, 12, 31), "total", 12))
    assert _row(total, "gross_profit")["values"] == [D("6000.00")]
    assert _row(total, "opex_total")["values"] == [D("2800.00")]
    assert _row(total, "net_income")["values"] == [D("3200.00")]   # the closing entry is left out
    rent = _row(total, "acct:6020")
    assert rent["codes"] == ["6020"] and rent["values"] == [D("2300.00")] and rent["kind"] == "account"
    assert rent["drill"] == [{"start": date(2026, 10, 1), "end": date(2026, 12, 31)}]


def test_pct_change_zero_and_negative_base():
    cols = [columns_for(date(2026, 10, 1), date(2026, 12, 31), "total", 12)[0],
            columns_for(date(2025, 4, 1), date(2025, 6, 30), "total", 12)[0]]
    report = with_change(profit_and_loss(ENTRIES, CHART, cols), 0, 1)
    assert [c["kind"] for c in report["columns"]] == ["amount", "amount", "change", "pct"]
    assert _row(report, "net_sales")["values"] == [D("10000.00"), D("5000.00"), D("5000.00"), D("100.00")]
    assert _row(report, "opex_total")["values"][2:] == [D("2800.00"), None]           # nothing before: no %
    neg = with_change({"columns": report["columns"][:2], "rows": [
        {"key": "x", "label": "x", "level": 0, "kind": "total", "codes": [], "values": [D("-50"), D("-100")],
         "drill": [None, None]}]}, 0, 1)
    assert neg["rows"][0]["values"][2:] == [D("50.00"), D("50.00")]                     # loss halved: +50%
    assert neg["rows"][0]["drill"] == [None, None, None, None]


def test_balance_sheet_balances_with_virtual_close():
    report = balance_sheet(ENTRIES, CHART, [date(2026, 12, 31), date(2026, 9, 30)], 12, "3020")
    assert _row(report, "acct:1010")["values"] == [D("103000.00"), D("105000.00")]
    assert _row(report, "acct:1510")["values"] == [D("-500.00"), D("0.00")]
    assert _row(report, "prior_earnings")["values"] == [D("5000.00"), D("5000.00")]
    assert _row(report, "current_earnings")["values"] == [D("3200.00"), D("0.00")]
    assert _row(report, "assets_total")["values"] == [D("114180.00"), D("105000.00")]
    assert _row(report, "le_total")["values"] == [D("114180.00"), D("105000.00")]
    assert report["balanced"] is True
    assert _row(report, "acct:1010")["drill"][0] == {"start": None, "end": date(2026, 12, 31)}
    assert _row(report, "prior_earnings")["drill"][0] == {"start": None, "end": date(2025, 12, 31)}
    assert _row(report, "current_earnings")["drill"][0] == {"start": date(2026, 1, 1), "end": date(2026, 12, 31)}


def test_bs_virtual_close_fiscal_june():
    entries = ENTRIES + [E("doc:m:sale", date(2026, 3, 10), ("1010", "700", "0"), ("4010", "0", "700"))]
    june = balance_sheet(entries, CHART, [date(2026, 12, 31)], 6, "3020")
    assert _row(june, "prior_earnings")["values"] == [D("5700.00")]
    assert _row(june, "current_earnings")["values"] == [D("3200.00")]
    dec = balance_sheet(entries, CHART, [date(2026, 12, 31)], 12, "3020")
    assert _row(dec, "current_earnings")["values"] == [D("3900.00")]
    assert june["balanced"] and dec["balanced"]


def test_shape_nonzero_keeps_totals():
    report = profit_and_loss(ENTRIES, CHART, columns_for(date(2026, 10, 1), date(2026, 12, 31), "month", 12))
    report = with_change({**report, "columns": report["columns"][:2],
                          "rows": [{**r, "values": r["values"][:2], "drill": r["drill"][:2]} for r in report["rows"]]},
                         0, 1)
    shaped = shape(report, nonzero=True, thousands=True)
    keys = [r["key"] for r in shaped["rows"]]
    assert "acct:6020" in keys and "acct:4020" not in keys            # sales returns: zero everywhere
    assert "net_income" in keys and "opex" in keys                   # headers / totals stay
    assert _row(shaped, "net_sales")["values"][0] == D("10.00")
    assert _row(shaped, "net_sales")["values"][3] is None            # % untouched (base 0 → blank)
    assert _row(shaped, "net_income")["values"][2] == D("8.50")      # change scaled: 6000 − (−2500)


def test_gl_detail_opening_closing_and_party_filter():
    rows = gl_detail(ENTRIES, CHART, date(2026, 10, 1), date(2026, 12, 31), 12)
    cash = next(r for r in rows if r["code"] == "1010")
    assert cash["opening"] == D("105000.00") and cash["closing"] == D("103000.00")
    assert [l["entry_id"] for l in cash["lines"]] == ["doc:r1:buy"]
    assert cash["lines"][0]["balance"] == D("103000.00")
    rent = next(r for r in rows if r["code"] == "6020")
    assert rent["opening"] == D("0.00")                       # P&L opens at the fiscal year start
    assert all(r["code"] != "3900" for r in rows)             # closing entries left out
    ar = gl_detail(ENTRIES, CHART, date(2026, 10, 1), date(2026, 12, 31), 12, account="1100")
    assert [r["code"] for r in ar] == ["1100"] and ar[0]["closing"] == D("0.00")
    kal = gl_detail(ENTRIES, CHART, date(2026, 10, 1), date(2026, 12, 31), 12, party="kalayaan")
    assert {l["entry_id"] for r in kal for l in r["lines"]} == {"doc:s1:sale", "pay:rcpt:r9"}
    assert kal[0]["lines"][0]["ref"]["kind"] == "document"


def test_transaction_list_by_date():
    rows = transaction_list(ENTRIES, CHART, date(2026, 10, 1), date(2026, 12, 31))
    assert [r["entry_id"] for r in rows] == ["doc:s1:sale", "doc:b1:buy", "doc:r1:buy", "dep:a1:2026-11", "je:adj1",
                                             "pay:rcpt:r9"]
    assert rows[0]["amount"] == D("11200.00") and rows[0]["accounts"] == ["1100", "4010", "2100"]
    assert [r["entry_id"] for r in transaction_list(ENTRIES, CHART, date(2026, 10, 1), date(2026, 12, 31),
                                                    account="6020")] == ["doc:r1:buy", "je:adj1"]


def test_adjusted_tb_and_aje_report():
    tb = adjusted_tb(ENTRIES, CHART, date(2026, 12, 31), 12, "3020", {"je:adj1"})
    assert [c["key"] for c in tb["columns"]] == ["unadjusted", "adjustments", "adjusted"]
    assert _row(tb, "acct:6020")["values"] == [D("2000.00"), D("300.00"), D("2300.00")]
    assert _row(tb, "acct:6100")["values"] == [D("0.00"), D("500.00"), D("500.00")]
    assert _row(tb, "acct:2010")["values"] == [D("-4480.00"), D("-300.00"), D("-4780.00")]
    assert _row(tb, "prior_earnings")["values"] == [D("-5000.00"), D("0.00"), D("-5000.00")]
    assert _row(tb, "total")["values"] == [D("0.00"), D("0.00"), D("0.00")]
    assert all(r["key"] != "acct:3900" for r in tb["rows"])
    aje = adjusting_entries(ENTRIES, CHART, date(2026, 10, 1), date(2026, 12, 31), {"je:adj1"})
    assert [a["entry_id"] for a in aje] == ["dep:a1:2026-11", "je:adj1"]
    assert aje[1]["kind"] == "Adjusting journal entry" and aje[0]["kind"] == "Depreciation"
    assert aje[1]["lines"][0] == {"code": "6020", "name": "Rent", "debit": D("300"), "credit": D("0")}


def test_check_entries_and_manual():
    bad = [E("bank:l1", date(2026, 11, 2), ("1020", "0", "150"), ("6999", "150", "0")),
           E("je:x", date(2026, 11, 3), ("9999", "10", "0"), ("1010", "0", "10")),
           Entry("je:y", date(2026, 11, 4), "GJ", "R", "", "", "p", "manual",
                 (Line("1010", D("10")), Line("4010", credit=D("9"))))]
    rows = check_entries(ENTRIES + bad, CHART)
    assert [(r["entry_id"], r["problem"]) for r in rows] == [
        ("bank:l1", "inactive_account"), ("je:x", "missing_account"), ("je:y", "unbalanced")]
    assert rows[0]["ref"] == {"kind": "bank_line", "id": "l1"}
    manual = check_manual([
        {"id": "a", "entry_date": date(2026, 11, 5), "reference": "A", "lines": [
            {"account_code": "1010", "debit": "10", "credit": "0"}]},
        {"id": "b", "entry_date": date(2026, 11, 5), "reference": "B", "lines": [
            {"account_code": "1010", "debit": "10", "credit": "10"}, {"account_code": "4010", "debit": "0",
                                                                    "credit": "0"}]},
        {"id": "c", "entry_date": date(2026, 11, 5), "reference": "C", "lines": [
            {"account_code": "1010", "debit": "10", "credit": "0"}, {"account_code": "6999", "debit": "0",
                                                                    "credit": "x"}]},
        {"id": "ok", "entry_date": date(2026, 11, 5), "reference": "", "lines": [
            {"account_code": "1010", "debit": "10", "credit": "0"}, {"account_code": "4010", "debit": "0",
                                                                    "credit": "10"}]},
    ], CHART)
    assert [(r["entry_id"], r["problem"]) for r in manual] == [
        ("je:a", "too_few_lines"), ("je:a", "unbalanced"), ("je:b", "one_side"), ("je:b", "one_side"),
        ("je:c", "bad_amount"), ("je:c", "inactive_account"), ("je:c", "unbalanced")]


def test_entry_refs():
    assert entry_ref("doc:abc:sale") == {"kind": "document", "id": "abc"}
    assert entry_ref("pay:rcpt:abc") == {"kind": "document", "id": "abc"}
    assert entry_ref("pay:paid:abc") == {"kind": "document", "id": "abc"}
    assert entry_ref("pay:bank:l1") == {"kind": "bank_line", "id": "l1"}
    assert entry_ref("bank:l1") == {"kind": "bank_line", "id": "l1"}
    assert entry_ref("je:j1") == {"kind": "journal_entry", "id": "j1"}
    assert entry_ref("dep:a1:2026-11") == {"kind": "asset", "id": "a1"}
    assert entry_ref("tax:2550Q:2026Q4:close") == {"kind": "tax", "id": "tax:2550Q:2026Q4:close"}
    assert entry_ref("fix:doc:abc:buy:rev") == {"kind": "document", "id": "abc"}
    assert entry_ref("inv:2026Q4") == {"kind": "system", "id": "inv:2026Q4"}


def test_drill_sums_to_cell():
    total = profit_and_loss(ENTRIES, CHART, columns_for(date(2026, 10, 1), date(2026, 12, 31), "total", 12))
    for key in ("acct:6020", "opex_total", "net_sales", "net_income"):
        row = _row(total, key)
        got = postings(ENTRIES, CHART, row["codes"], row["drill"][0]["start"], row["drill"][0]["end"])
        assert abs(got["total"]) == abs(row["values"][0]), key
    bs = balance_sheet(ENTRIES, CHART, [date(2026, 12, 31)], 12, "3020")
    row = _row(bs, "prior_earnings")
    got = postings(ENTRIES, CHART, row["codes"], row["drill"][0]["start"], row["drill"][0]["end"])
    assert -got["total"] == row["values"][0]
    capped = postings(ENTRIES, CHART, ["1010"], None, date(2026, 12, 31), limit=2)
    assert len(capped["lines"]) == 2 and capped["truncated"] is True and capped["total"] == D("103000.00")


def test_kpis():
    pnl = profit_and_loss(ENTRIES, CHART, columns_for(date(2026, 10, 1), date(2026, 12, 31), "total", 12))
    bs = balance_sheet(ENTRIES, CHART, [date(2026, 12, 31)], 12, "3020")
    k = kpis(pnl, bs, CHART)
    assert k["gross_margin"] == D("60.00") and k["net_margin"] == D("32.00") and k["opex_ratio"] == D("28.00")
    assert k["current_ratio"] == D("19.18")      # (103000 + 11200 + 480) / 5980
    assert k["quick_ratio"] == D("19.10")        # (103000 + 11200) / 5980
    cols = columns_for(date(2026, 10, 1), date(2026, 12, 31), "total", 12)
    empty = kpis(profit_and_loss([], CHART, cols), balance_sheet([], CHART, [date(2026, 12, 31)], 12, "3020"), CHART)
    assert empty["gross_margin"] is None and empty["current_ratio"] is None


def test_cash_flow_reconciles():
    rows = cash_flow(ENTRIES, CHART, date(2026, 10, 1), date(2026, 12, 31), 12, "3020")
    by = {r["key"]: r["amount"] for r in rows}
    assert by["ni"] == D("3200.00") and by["dep"] == D("500.00")
    assert by["cash_open"] == D("105000.00") and by["cash_end"] == D("114200.00")
    assert by["net"] == D("9200.00")
    assert by["op_total"] + by["inv_total"] + by["fin_total"] == by["net"]


def test_check_window_caps_the_engine_work():
    import pytest

    from app.services.accounting.compute.reports import check_window, latest_allowed

    today = date(2026, 10, 17)
    assert latest_allowed(today, 12) == date(2027, 12, 31)
    assert latest_allowed(today, 6) == date(2028, 6, 30)
    check_window(date(2026, 10, 1), date(2027, 12, 31), today, 12)
    check_window(None, date(2026, 12, 31), today, 12)                    # drill to date from the beginning
    for start, end in ((None, date(9999, 12, 31)), (date(2026, 1, 1), date(2028, 1, 1)), (date(1900, 1, 1), date(2026, 1, 1)),
                       (None, date(1999, 12, 31)), (date(2026, 12, 1), date(2026, 11, 1)),
                       (date(2000, 1, 1), date(2026, 12, 31))):
        with pytest.raises(ValueError):
            check_window(start, end, today, 12)


def test_no_negative_zero():
    report = profit_and_loss(ENTRIES, CHART, columns_for(date(2026, 10, 1), date(2026, 12, 31), "total", 12))
    assert all(str(v) != "-0.00" for r in report["rows"] for v in r["values"] if v is not None)
    bs = balance_sheet([], CHART, [date(2026, 12, 31)], 12, "3020")
    assert all(str(v) != "-0.00" for r in bs["rows"] for v in r["values"] if v is not None)


def test_corrections_of_adjusting_entries_are_adjustments():
    # An adjusting JE (and a depreciation entry) in a closed month, later changed: the frozen entry stays, and the
    # correcting reversal and repost (fix:<id>:rev / :new, source "correction") must count as adjustments too.
    entries = [e for e in ENTRIES if not e.id.startswith("close:")] + [
        E("fix:je:adj1:rev", date(2026, 12, 20), ("6020", "0", "300"), ("2010", "300", "0"), source="correction"),
        E("fix:je:adj1:new", date(2026, 12, 20), ("6020", "450", "0"), ("2010", "0", "450"), source="correction"),
        E("fix:dep:a1:2026-11:rev", date(2026, 12, 20), ("6100", "0", "500"), ("1510", "500", "0"),
          source="correction"),
        E("fix:dep:a1:2026-11:new", date(2026, 12, 20), ("6100", "600", "0"), ("1510", "0", "600"),
          source="correction"),
    ]
    tb = adjusted_tb(entries, CHART, date(2026, 12, 31), 12, "3020", {"je:adj1"})
    assert _row(tb, "acct:6020")["values"] == [D("2000.00"), D("450.00"), D("2450.00")]
    assert _row(tb, "acct:6100")["values"] == [D("0.00"), D("600.00"), D("600.00")]
    assert _row(tb, "total")["values"] == [D("0.00"), D("0.00"), D("0.00")]
    aje = adjusting_entries(entries, CHART, date(2026, 10, 1), date(2026, 12, 31), {"je:adj1"})
    kinds = {a["entry_id"]: a["kind"] for a in aje}
    assert kinds["fix:je:adj1:new"] == "Adjusting journal entry" and kinds["fix:dep:a1:2026-11:rev"] == "Depreciation"


def test_drill_codes_are_never_silently_cut():
    import pytest

    from app.services.accounting.compute.reports import MAX_DRILL_CODES, drill_codes

    many = [str(5000 + n) for n in range(250)]  # a chart with 250 P&L accounts: Net income drills into all of them
    assert drill_codes(",".join(many)) == many
    assert drill_codes("4010,,4020") == ["4010", "4020"]
    with pytest.raises(ValueError):
        drill_codes(",".join(str(10000 + n) for n in range(MAX_DRILL_CODES + 1)))


def test_cash_balance_sums_cash_bank_and_ewallet_up_to_the_date():
    assert cash_balance(ENTRIES, CHART, date(2026, 12, 19)) == D("103000.00")
    assert cash_balance(ENTRIES, CHART, date(2026, 12, 31)) == D("114200.00")
    assert cash_balance(ENTRIES, CHART, date(2024, 12, 31)) == D("0.00")
