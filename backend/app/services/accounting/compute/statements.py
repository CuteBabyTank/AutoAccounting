"""Year end: closing entries, post-closing trial balance and the financial statements from the books (pure).

PFRS for Small Entities presentation, no comparatives: Statement of Financial Position, Income Statement,
Statement of Changes in Equity, and Statement of Cash Flows (indirect). The year-end adjustments (depreciation,
inventory count, income tax from the annual return) are already in the entries; closing entries are dated the last
day of the fiscal year in the General Journal.
"""

from datetime import date
from decimal import Decimal

from app.services.accounting.books.chart import Chart, ChartAccount
from app.services.accounting.compute.books import Entry, _cr, _dr, make_entry
from app.services.accounting.compute.due_dates import quarter_end, quarter_start
from app.services.accounting.compute.money import ZERO, c2, total

STATEMENT_TABS = ("PCTB", "SFP", "IS", "SCE", "SCF")
_CASH = {"cash", "bank", "ewallet"}
_NON_CURRENT = {"ppe", "accum_dep"}
_REVENUE = {"sales", "sales_returns"}
_EQUITY = {"capital", "retained_earnings", "drawings", "income_summary"}


def is_closing(e: Entry) -> bool:
    return e.id.startswith("close:")


def _root(chart: Chart, code: str) -> ChartAccount | None:
    """The account a sub-account rolls up to (the nearest one with a system key, else the top parent)."""
    account = chart.get(code)
    seen: set[str] = set()
    while account is not None and account.system_key is None and account.parent_code and account.code not in seen:
        seen.add(account.code)
        parent = chart.get(account.parent_code)
        if parent is None:
            break
        account = parent
    return account


def _key(chart: Chart, code: str) -> str:
    root = _root(chart, code)
    return (root.system_key or "") if root else ""


def _is_loan(chart: Chart, code: str) -> bool:
    root = _root(chart, code)
    return root is not None and root.type == "liability" and "loan" in root.name.lower()


def _sum(entries, keep) -> dict[str, Decimal]:
    out: dict[str, Decimal] = {}
    for e in entries:
        if keep(e):
            for l in e.lines:
                out[l.account] = c2(out.get(l.account, ZERO) + l.debit - l.credit)
    return out


def fiscal_window(fiscal_year: int, fye: int) -> tuple[date, date]:
    return quarter_start(fiscal_year, 1, fye), quarter_end(fiscal_year, 4, fye)


def closing_entries(entries: list[Entry], chart: Chart, fiscal_year: int, fye: int, closing_account: str,
                    taxpayer_type: str) -> list[Entry]:
    """Close the year's income, cost and expense accounts to Income summary, Income summary to retained earnings
    (corporation) or capital, and Drawings to capital."""
    start, end = fiscal_window(fiscal_year, fye)
    activity = _sum(entries, lambda e: start <= e.date <= end and not is_closing(e))
    pnl = {code: bal for code, bal in sorted(activity.items())
           if bal != 0 and (a := chart.get(code)) is not None and a.type in ("income", "cost", "expense")}
    summary = chart.code("income_summary")
    net_income = c2(-total(pnl.values()))
    out: list[Entry] = []
    entry = make_entry(f"close:{fiscal_year}:pnl", end, "GJ", f"Closing FY {fiscal_year}", ("", ""),
                       "To close income and expense accounts to income summary", "closing",
                       *(_cr(code, bal) for code, bal in pnl.items()), _cr(summary, net_income))
    if entry:
        out.append(entry)
    entry = make_entry(f"close:{fiscal_year}:summary", end, "GJ", f"Closing FY {fiscal_year}", ("", ""),
                       "To close income summary to " + chart.name(closing_account).lower(), "closing",
                       _dr(summary, net_income), _cr(closing_account, net_income))
    if entry:
        out.append(entry)
    if taxpayer_type != "corporation":
        drawings = chart.code("drawings")
        balance = c2(activity.get(drawings, ZERO))  # this year's drawings; earlier years' were closed then
        entry = make_entry(f"close:{fiscal_year}:drawings", end, "GJ", f"Closing FY {fiscal_year}", ("", ""),
                           "To close drawings to capital", "closing",
                           _cr(drawings, balance), _dr(closing_account, balance))
        if entry:
            out.append(entry)
    return out


def _row(key: str, line: str, amount: Decimal | None = None, level: int = 0) -> dict:
    return {"key": key, "line": ("    " * level) + line, "amount": "" if amount is None else c2(amount)}


def build_statements(entries: list[Entry], chart: Chart, fiscal_year: int, fye: int, closing_account: str,
                     taxpayer_type: str, books_start: date | None) -> tuple[dict[str, list[dict]], list[str]]:
    """Tabs PCTB / SFP / IS / SCE / SCF for the fiscal year. ``entries`` include the closing entries."""
    start, end = fiscal_window(fiscal_year, fye)
    warnings: list[str] = []
    # The year opens with everything before it, plus opening balances entered inside it (books started mid-year).
    opening_in_year = lambda e: start <= e.date <= end and e.source == "opening"  # noqa: E731
    before = _sum(entries, lambda e: e.date < start or opening_in_year(e))
    year = _sum(entries, lambda e: start <= e.date <= end and not is_closing(e) and e.source != "opening")
    after = _sum(entries, lambda e: e.date <= end)
    # Earlier years' income and expense balances sit in equity at the start of the year (virtually closed).
    carried = c2(total(b for code, b in before.items()
                       if (a := chart.get(code)) is not None and a.type in ("income", "cost", "expense")))
    for code in [c for c in before if (a := chart.get(c)) is not None and a.type in ("income", "cost", "expense")]:
        before.pop(code)
    if carried:
        before[closing_account] = c2(before.get(closing_account, ZERO) + carried)

    def accounts(kind):
        return [a for a in chart.accounts if a.type == kind]

    # --- Income statement -------------------------------------------------------------------------------------
    def credit(code):  # income shown positive
        return c2(-year.get(code, ZERO))

    revenue = [a for a in accounts("income") if _key(chart, a.code) in _REVENUE]
    other_income = [a for a in accounts("income") if _key(chart, a.code) not in _REVENUE]
    costs = accounts("cost")
    tax_code = chart.code("income_tax")
    expenses = [a for a in accounts("expense") if a.code != tax_code]
    net_sales = total(credit(a.code) for a in revenue)
    cost_of_sales = total(year.get(a.code, ZERO) for a in costs)
    gross_profit = c2(net_sales - cost_of_sales)
    opex = total(year.get(a.code, ZERO) for a in expenses)
    operating = c2(gross_profit - opex)
    other = total(credit(a.code) for a in other_income)
    before_tax = c2(operating + other)
    income_tax = c2(year.get(tax_code, ZERO))
    net_income = c2(before_tax - income_tax)
    is_rows = [_row("rev", "Revenue")]
    is_rows += [_row(f"rev:{a.code}", a.name, credit(a.code), 1) for a in revenue if year.get(a.code)]
    is_rows += [_row("net_sales", "Net sales", net_sales),
                _row("cos", "Cost of sales", cost_of_sales),
                _row("gross_profit", "Gross profit", gross_profit),
                _row("opex", "Operating expenses")]
    is_rows += [_row(f"exp:{a.code}", a.name, year.get(a.code), 1) for a in expenses if year.get(a.code)]
    is_rows += [_row("opex_total", "Total operating expenses", opex),
                _row("operating", "Operating income (loss)", operating)]
    is_rows += [_row(f"oi:{a.code}", a.name, credit(a.code), 1) for a in other_income if year.get(a.code)]
    is_rows += [_row("before_tax", "Income (loss) before income tax", before_tax),
                _row("income_tax", "Income tax expense", income_tax),
                _row("net_income", "NET INCOME (LOSS)", net_income)]

    # --- Statement of financial position ----------------------------------------------------------------------
    pre_close = _sum(entries, lambda e: e.date <= end and not is_closing(e))
    it_payable = chart.code("it_payable")
    current, non_current, cur_liab, nc_liab = [], [], [], []
    for a in chart.accounts:
        bal = c2(after.get(a.code, ZERO))
        if bal == 0 or a.type not in ("asset", "liability"):
            continue
        key = _key(chart, a.code)
        if a.type == "asset":
            (non_current if key in _NON_CURRENT else current).append((a, bal))
        elif a.code == it_payable and bal > 0:  # excess credits: an asset
            current.append((ChartAccount(a.code, "Excess income tax credits", "asset"), bal))
        else:
            (nc_liab if _is_loan(chart, a.code) else cur_liab).append((a, c2(-bal)))
    equity = [(a, c2(-after.get(a.code, ZERO))) for a in chart.accounts
              if a.type == "equity" and after.get(a.code)]
    total_assets = total(b for _, b in current + non_current)
    total_liabilities = total(b for _, b in cur_liab + nc_liab)
    total_equity = total(b for _, b in equity)
    sfp = [_row("assets", "ASSETS"), _row("ca", "Current assets", level=1)]
    sfp += [_row(f"a:{a.code}", a.name, b, 2) for a, b in current]
    sfp += [_row("ca_total", "Total current assets", total(b for _, b in current), 1),
            _row("nca", "Non-current assets", level=1)]
    sfp += [_row(f"a:{a.code}", a.name, b, 2) for a, b in non_current]
    sfp += [_row("nca_total", "Total non-current assets", total(b for _, b in non_current), 1),
            _row("assets_total", "TOTAL ASSETS", total_assets),
            _row("liab", "LIABILITIES AND EQUITY"), _row("cl", "Current liabilities", level=1)]
    sfp += [_row(f"l:{a.code}", a.name, b, 2) for a, b in cur_liab]
    sfp += [_row("cl_total", "Total current liabilities", total(b for _, b in cur_liab), 1)]
    if nc_liab:
        sfp += [_row("ncl", "Non-current liabilities", level=1)]
        sfp += [_row(f"l:{a.code}", a.name, b, 2) for a, b in nc_liab]
    sfp += [_row("liab_total", "Total liabilities", total_liabilities, 1), _row("eq", "Equity", level=1)]
    sfp += [_row(f"e:{a.code}", a.name, b, 2) for a, b in equity]
    sfp += [_row("eq_total", "Total equity", total_equity, 1),
            _row("le_total", "TOTAL LIABILITIES AND EQUITY", c2(total_liabilities + total_equity))]
    if c2(total_assets) != c2(total_liabilities + total_equity):
        warnings.append(f"The statement of financial position doesn't balance (assets ₱{total_assets:,.2f}, "
                        f"liabilities and equity ₱{total_liabilities + total_equity:,.2f}).")

    # --- Statement of changes in equity -----------------------------------------------------------------------
    sce: list[dict] = []
    for a in [a for a in chart.accounts if a.type == "equity" and _key(chart, a.code) != "income_summary"]:
        opening = c2(-before.get(a.code, ZERO))
        closing = c2(-after.get(a.code, ZERO))
        if opening == 0 and closing == 0 and not year.get(a.code):
            continue
        moved = c2(-year.get(a.code, ZERO))
        closed = c2(closing - opening - moved)  # net income / drawings closed into it at year end
        label = a.name
        sce += [_row(f"{a.code}:open", f"{label}, beginning", opening)]
        if moved:
            sce += [_row(f"{a.code}:moves", "Additional investments (withdrawals)" if _key(chart, a.code) != "drawings"
                         else "Drawings during the year", moved, 1)]
        if closed and a.code == closing_account:
            sce += [_row(f"{a.code}:ni", "Net income (loss) for the year", net_income, 1)]
            if c2(closed - net_income):
                sce += [_row(f"{a.code}:dr", "Drawings closed", c2(closed - net_income), 1)]
        elif closed:
            sce += [_row(f"{a.code}:closed", "Closed at year end", closed, 1)]
        sce += [_row(f"{a.code}:end", f"{label}, end", closing)]
    sce += [_row("total", "TOTAL EQUITY, END", total_equity)]

    # --- Statement of cash flows (indirect) -------------------------------------------------------------------
    def change(code):  # increase in the debit balance over the year (closing entries excluded)
        return c2(pre_close.get(code, ZERO) - before.get(code, ZERO))

    cash_codes = [a.code for a in chart.accounts if _key(chart, a.code) in _CASH]
    accum = [a.code for a in chart.accounts if _key(chart, a.code) == "accum_dep"]
    ppe = [a.code for a in chart.accounts if _key(chart, a.code) == "ppe"]
    depreciation = c2(-total(change(c) for c in accum))
    working, investing, financing = [], [], []
    for a in chart.accounts:
        if a.code in cash_codes or a.code in accum or a.type not in ("asset", "liability", "equity"):
            continue
        delta = change(a.code)
        if delta == 0:
            continue
        if a.code in ppe:
            investing.append(_row(f"inv:{a.code}", f"Acquisition of {a.name.lower()}", -delta, 1))
        elif a.type == "equity" or _is_loan(chart, a.code):
            name = "Drawings" if _key(chart, a.code) == "drawings" else a.name
            financing.append(_row(f"fin:{a.code}", name, -delta, 1))
        else:
            label = (f"(Increase) decrease in {a.name.lower()}" if a.type == "asset"
                     else f"Increase (decrease) in {a.name.lower()}")
            working.append(_row(f"op:{a.code}", label, -delta, 2))
    operating_cash = c2(net_income + depreciation + total(r["amount"] for r in working))
    investing_cash = c2(total(r["amount"] for r in investing))
    financing_cash = c2(total(r["amount"] for r in financing))
    cash_open = c2(total(before.get(c, ZERO) for c in cash_codes))
    cash_close = c2(total(after.get(c, ZERO) for c in cash_codes))
    scf = [_row("op", "Cash flows from operating activities"),
           _row("ni", "Net income (loss)", net_income, 1),
           _row("dep", "Depreciation", depreciation, 1),
           _row("wc", "Changes in working capital", level=1)] + working + [
        _row("op_total", "Net cash from (used in) operating activities", operating_cash),
        _row("inv", "Cash flows from investing activities")] + investing + [
        _row("inv_total", "Net cash from (used in) investing activities", investing_cash),
        _row("fin", "Cash flows from financing activities")] + financing + [
        _row("fin_total", "Net cash from (used in) financing activities", financing_cash),
        _row("net", "Net increase (decrease) in cash", c2(operating_cash + investing_cash + financing_cash)),
        _row("cash_open", "Cash, beginning", cash_open),
        _row("cash_end", "Cash, end", cash_close)]
    if c2(cash_open + operating_cash + investing_cash + financing_cash) != cash_close:
        warnings.append("The statement of cash flows doesn't reconcile to the cash accounts; check the chart's "
                        "account types.")

    # --- Post-closing trial balance ---------------------------------------------------------------------------
    pctb = [{"key": code, "code": code, "account": chart.name(code),
             "debit": bal if bal > 0 else ZERO, "credit": -bal if bal < 0 else ZERO}
            for code, bal in sorted(after.items()) if bal != 0]
    pctb.append({"key": "~total", "code": "", "account": "Total", "debit": total(r["debit"] for r in pctb),
                 "credit": total(r["credit"] for r in pctb)})
    leftover = [r["account"] for r in pctb[:-1] if (a := chart.get(r["key"])) and a.type in ("income", "cost", "expense")]
    if leftover:
        warnings.append(f"Income or expense accounts still have balances after closing: {', '.join(leftover)}.")
    if books_start and start < books_start <= end:
        warnings.append(f"The books start on {books_start:%B %-d, %Y}, so the income statement and cash flows cover "
                        "only the months since then; the opening balances stand in for the months before.")
    return {"PCTB": pctb, "SFP": sfp, "IS": is_rows, "SCE": sce, "SCF": scf}, warnings
