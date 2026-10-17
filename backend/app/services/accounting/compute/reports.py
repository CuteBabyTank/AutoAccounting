"""Live reports from the books' entries (pure): P&L by column, comparisons, Balance Sheet, GL detail, transaction
list, adjusted trial balance, adjusting entries, invalid-transaction checks, drill-down postings, KPIs, cash flow.

Closing entries (and corrections of them) are left out everywhere: earlier fiscal years' income and expense are
shown as "Prior years' earnings not yet closed" instead, so every report balances whether or not a year has been
closed. Amounts are debit-positive internally; P&L income and BS liabilities / equity are shown positive.

Report shape (P&L, Balance Sheet, adjusted TB)::

    {"columns": [{"key", "label", "start", "end", "kind": "amount" | "change" | "pct"}],
     "rows": [{"key", "label", "level", "kind": "header" | "account" | "total", "codes": [...],
               "values": [Decimal | None per column], "drill": [{"start", "end"} | None per column]}]}

``drill`` is the window whose postings of ``codes`` add up to the cell (``start`` None = from the beginning).
"""

import calendar
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from app.services.accounting.books.chart import Chart
from app.services.accounting.compute.books import Entry
from app.services.accounting.compute.due_dates import quarter_end, quarter_start
from app.services.accounting.compute.money import ZERO, c2, total
from app.services.accounting.compute.statements import _is_loan, _key
from app.services.accounting.periods import period_for

PNL_TYPES = ("income", "cost", "expense")
_REVENUE = {"sales", "sales_returns"}
_CASH = {"cash", "bank", "ewallet"}
_NON_CURRENT = {"ppe", "accum_dep"}
_QUICK = {"cash", "bank", "ewallet", "ar", "cwt"}
ADJUSTING_SOURCES = {"depreciation": "Depreciation", "inventory": "Inventory count"}
MAX_COLUMNS = 24


@dataclass(frozen=True)
class Column:
    key: str
    label: str
    start: date | None
    end: date


# --- windows ---------------------------------------------------------------------------------------------------------

def _month_end(d: date) -> date:
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def _add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    y, m = d.year + m // 12, m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def fy_start(d: date, fye: int) -> date:
    return quarter_start(period_for(d, fye).fiscal_year, 1, fye)


def _quarter_label(fy: int, q: int, fye: int) -> str:
    return f"Q{q} {fy}" if fye == 12 else f"Q{q} FY{fy}"


def columns_for(start: date, end: date, by: str, fye: int) -> list[Column]:
    """One column for the range, or one per calendar month / fiscal quarter (clipped to the range)."""
    if by == "total":
        return [Column("total", f"{start:%b %-d, %Y} – {end:%b %-d, %Y}", start, end)]
    out: list[Column] = []
    cursor = start
    while cursor <= end:
        if by == "month":
            last = min(_month_end(cursor), end)
            out.append(Column(f"m{cursor:%Y-%m}", f"{cursor:%b %Y}", cursor, last))
        else:
            p = period_for(cursor, fye)
            last = min(quarter_end(p.fiscal_year, p.quarter, fye), end)
            out.append(Column(f"q{p.fiscal_year}-{p.quarter}", _quarter_label(p.fiscal_year, p.quarter, fye),
                              cursor, last))
        cursor = last + timedelta(days=1)
    return out


def prior_window(start: date, end: date, mode: str) -> tuple[date, date]:
    """The comparison window: the same span just before (``period``) or one year earlier (``year``)."""
    if mode == "year":
        last = _month_end(_add_months(date(end.year, end.month, 1), -12)) if end == _month_end(end) \
            else _add_months(end, -12)
        return _add_months(start, -12), last
    if start.day == 1 and end == _month_end(end):  # whole months: the same number of months before
        months = (end.year - start.year) * 12 + end.month - start.month + 1
        first = _add_months(start, -months)
        return first, start - timedelta(days=1)
    days = (end - start).days + 1
    return start - timedelta(days=days), start - timedelta(days=1)


# --- entries ---------------------------------------------------------------------------------------------------------

def is_closing(e: Entry) -> bool:
    return e.id.startswith("close:") or e.id.startswith("fix:close:")


def _live(entries: Iterable[Entry]) -> list[Entry]:
    return [e for e in entries if not is_closing(e)]


def entry_ref(entry_id: str) -> dict:
    """What an entry traces back to: a document, bank line, journal entry, asset, tax return or the engine itself."""
    if entry_id.startswith("fix:") and entry_id.rsplit(":", 1)[-1] in ("rev", "new"):
        return entry_ref(entry_id[4:].rsplit(":", 1)[0])
    parts = entry_id.split(":")
    head = parts[0]
    if head == "doc" and len(parts) >= 2:
        return {"kind": "document", "id": parts[1]}
    if head == "pay" and len(parts) >= 3:
        return {"kind": "bank_line" if parts[1] == "bank" else "document", "id": parts[2]}
    if head == "bank" and len(parts) >= 2:
        return {"kind": "bank_line", "id": parts[1]}
    if head == "je" and len(parts) >= 2:
        return {"kind": "journal_entry", "id": parts[1]}
    if head == "dep" and len(parts) >= 2:
        return {"kind": "asset", "id": parts[1]}
    if head == "tax":
        return {"kind": "tax", "id": entry_id}
    return {"kind": "system", "id": entry_id}


def _sums(entries: Iterable[Entry], keep: Callable[[Entry], bool]) -> dict[str, Decimal]:
    out: dict[str, Decimal] = {}
    for e in entries:
        if keep(e):
            for l in e.lines:
                out[l.account] = out.get(l.account, ZERO) + l.debit - l.credit
    return {k: c2(v) for k, v in out.items()}


def _in(start: date | None, end: date) -> Callable[[Entry], bool]:
    return lambda e: (start is None or e.date >= start) and e.date <= end


def _pnl_codes(chart: Chart) -> list[str]:
    return [a.code for a in chart.accounts if a.type in PNL_TYPES]


def _shown(chart: Chart, kinds: tuple[str, ...], used: set[str]) -> list:
    return [a for a in chart.accounts if a.type in kinds and (a.active or a.code in used)]


def _row(key: str, label: str, level: int, kind: str, codes: list[str], values: list, drill: list) -> dict:
    return {"key": key, "label": label, "level": level, "kind": kind, "codes": codes, "values": values,
            "drill": drill}


def _col(c: Column, kind: str = "amount") -> dict:
    return {"key": c.key, "label": c.label, "start": c.start, "end": c.end, "kind": kind}


# --- profit and loss -------------------------------------------------------------------------------------------------

def profit_and_loss(entries: list[Entry], chart: Chart, columns: list[Column]) -> dict:
    live = _live(entries)
    sums = [_sums(live, _in(c.start, c.end)) for c in columns]
    used = {code for s in sums for code, v in s.items() if v}
    window = [{"start": c.start, "end": c.end} for c in columns]
    none = [None] * len(columns)
    tax = chart.code("income_tax")
    accounts = _shown(chart, PNL_TYPES, used)
    revenue = [a for a in accounts if a.type == "income" and _key(chart, a.code) in _REVENUE]
    other = [a for a in accounts if a.type == "income" and _key(chart, a.code) not in _REVENUE]
    costs = [a for a in accounts if a.type == "cost"]
    expenses = [a for a in accounts if a.type == "expense" and a.code != tax]

    def amount(codes: list[str], sign: int) -> list[Decimal]:
        return [c2(sign * total(s.get(code, ZERO) for code in codes)) for s in sums]

    def accounts_rows(group, sign: int) -> list[dict]:
        return [_row(f"acct:{a.code}", f"{a.code} {a.name}", 1, "account", [a.code], amount([a.code], sign), window)
                for a in group]

    def codes(group) -> list[str]:
        return [a.code for a in group]

    rev, cos, exp, oth = codes(revenue), codes(costs), codes(expenses), codes(other)
    rows = [_row("revenue", "Revenue", 0, "header", [], none, none)] + accounts_rows(revenue, -1)
    rows.append(_row("net_sales", "Net sales", 0, "total", rev, amount(rev, -1), window))
    rows += [_row("cos_header", "Cost of sales", 0, "header", [], none, none)] + accounts_rows(costs, 1)
    rows.append(_row("cos", "Total cost of sales", 0, "total", cos, amount(cos, 1), window))
    rows.append(_row("gross_profit", "Gross profit", 0, "total", rev + cos, amount(rev + cos, -1), window))
    rows += [_row("opex", "Operating expenses", 0, "header", [], none, none)] + accounts_rows(expenses, 1)
    rows.append(_row("opex_total", "Total operating expenses", 0, "total", exp, amount(exp, 1), window))
    rows.append(_row("operating", "Operating income (loss)", 0, "total", rev + cos + exp, amount(rev + cos + exp, -1),
                     window))
    if other:
        rows += [_row("other_header", "Other income", 0, "header", [], none, none)] + accounts_rows(other, -1)
        rows.append(_row("other_total", "Total other income", 0, "total", oth, amount(oth, -1), window))
    before = rev + cos + exp + oth
    rows.append(_row("before_tax", "Income (loss) before income tax", 0, "total", before, amount(before, -1), window))
    rows.append(_row("income_tax", "Income tax expense", 0, "total", [tax], amount([tax], 1), window))
    rows.append(_row("net_income", "Net income (loss)", 0, "total", before + [tax], amount(before + [tax], -1),
                     window))
    return {"columns": [_col(c) for c in columns], "rows": rows}


def with_change(report: dict, base: int, other: int) -> dict:
    """Append ₱ change (base − other) and % change ((base − other) / |other|, blank when other is 0)."""
    columns = report["columns"] + [
        {"key": "change", "label": "₱ change", "start": None, "end": None, "kind": "change"},
        {"key": "pct", "label": "% change", "start": None, "end": None, "kind": "pct"}]
    rows = []
    for r in report["rows"]:
        a, b = r["values"][base], r["values"][other]
        change = pct = None
        if a is not None and b is not None:
            change = c2(a - b)
            pct = c2(change / abs(b) * 100) if b != 0 else None
        rows.append({**r, "values": r["values"] + [change, pct], "drill": r["drill"] + [None, None]})
    return {**report, "columns": columns, "rows": rows}


def shape(report: dict, *, nonzero: bool, thousands: bool) -> dict:
    """Viewer options: drop account rows that are zero in every amount column; show amounts in thousands."""
    kinds = [c["kind"] for c in report["columns"]]
    rows = report["rows"]
    if nonzero:
        rows = [r for r in rows if r["kind"] != "account"
                or any(v for v, k in zip(r["values"], kinds) if k == "amount")]
    if thousands:
        rows = [{**r, "values": [c2(v / 1000) if v is not None and k != "pct" else v
                                 for v, k in zip(r["values"], kinds)]} for r in rows]
    return {**report, "rows": rows, "thousands": thousands}


# --- balance sheet ---------------------------------------------------------------------------------------------------

def balance_sheet(entries: list[Entry], chart: Chart, as_of: list[date], fye: int, closing_account: str) -> dict:
    live = _live(entries)
    pnl = set(_pnl_codes(chart))
    starts = [fy_start(d, fye) for d in as_of]
    sums = [_sums(live, _in(None, d)) for d in as_of]
    prior = [c2(-total(v for k, v in _sums(live, _in(None, s - timedelta(days=1))).items() if k in pnl))
             for s in starts]
    current = [c2(-total(v for k, v in _sums(live, _in(s, d)).items() if k in pnl)) for s, d in zip(starts, as_of)]
    used = {code for s in sums for code, v in s.items() if v}
    to_date = [{"start": None, "end": d} for d in as_of]
    none = [None] * len(as_of)

    def group(kind: str, sign: int) -> tuple[list[dict], list[str]]:
        accounts = _shown(chart, (kind,), used)
        rows = [_row(f"acct:{a.code}", f"{a.code} {a.name}", 1, "account", [a.code],
                     [c2(sign * s.get(a.code, ZERO)) for s in sums], to_date) for a in accounts]
        return rows, [a.code for a in accounts]

    def sum_of(codes: list[str], sign: int) -> list[Decimal]:
        return [c2(sign * total(s.get(code, ZERO) for code in codes)) for s in sums]

    assets, a_codes = group("asset", 1)
    liabilities, l_codes = group("liability", -1)
    equity, e_codes = group("equity", -1)
    total_assets = sum_of(a_codes, 1)
    total_liab = sum_of(l_codes, -1)
    total_equity = [c2(e + p + c) for e, p, c in zip(sum_of(e_codes, -1), prior, current)]
    le = [c2(a + b) for a, b in zip(total_liab, total_equity)]
    pnl_codes = sorted(pnl)
    rows = [_row("assets", "Assets", 0, "header", [], none, none), *assets,
            _row("assets_total", "Total assets", 0, "total", a_codes, total_assets, to_date),
            _row("liabilities", "Liabilities", 0, "header", [], none, none), *liabilities,
            _row("liab_total", "Total liabilities", 0, "total", l_codes, total_liab, to_date),
            _row("equity", "Equity", 0, "header", [], none, none), *equity,
            _row("prior_earnings", "Prior years' earnings not yet closed", 1, "account", pnl_codes, prior,
                 [{"start": None, "end": s - timedelta(days=1)} for s in starts]),
            _row("current_earnings", "Current year earnings", 1, "account", pnl_codes, current,
                 [{"start": s, "end": d} for s, d in zip(starts, as_of)]),
            _row("eq_total", "Total equity", 0, "total", [], total_equity, none),
            _row("le_total", "Total liabilities and equity", 0, "total", [], le, none)]
    del closing_account  # earlier years stay visible as their own row rather than folded into retained earnings
    columns = [{"key": f"d{d.isoformat()}", "label": f"As of {d:%b %-d, %Y}", "start": s, "end": d,
                "kind": "amount"} for d, s in zip(as_of, starts)]
    return {"columns": columns, "rows": rows, "balanced": all(a == b for a, b in zip(total_assets, le))}


# --- GL detail and transaction list ----------------------------------------------------------------------------------

def _party_match(e: Entry, party: str | None) -> bool:
    if not party:
        return True
    needle = party.strip().lower()
    names = [e.party_name, e.party_tin] + [x for l in e.lines for x in (l.party_name, l.party_tin)]
    return any(needle in (n or "").lower() for n in names)


def _line_out(e: Entry, debit: Decimal, credit: Decimal, balance: Decimal | None = None) -> dict:
    out = {"entry_id": e.id, "date": e.date, "book": e.book, "reference": e.reference,
           "party": e.party_name, "particulars": e.particulars, "debit": debit, "credit": credit,
           "ref": entry_ref(e.id)}
    if balance is not None:
        out["balance"] = balance
    return out


def gl_detail(entries: list[Entry], chart: Chart, start: date, end: date, fye: int, *, account: str | None = None,
              party: str | None = None) -> list[dict]:
    """Per account: opening balance (P&L accounts from the fiscal year start), each posting, closing balance."""
    live = [e for e in _live(entries) if _party_match(e, party)]
    year_start = fy_start(start, fye)
    out = []
    for a in chart.accounts:
        if account and a.code != account:
            continue
        opening_from = year_start if a.type in PNL_TYPES else None
        opening = c2(total(l.debit - l.credit for e in live if (opening_from is None or e.date >= opening_from)
                           and e.date < start for l in e.lines if l.account == a.code))
        lines, balance = [], opening
        for e in sorted((e for e in live if start <= e.date <= end), key=lambda e: (e.date, e.id)):
            for l in e.lines:
                if l.account == a.code:
                    balance = c2(balance + l.debit - l.credit)
                    lines.append(_line_out(e, l.debit, l.credit, balance))
        if lines or (opening and not party):
            out.append({"code": a.code, "name": a.name, "type": a.type, "opening": opening, "lines": lines,
                        "closing": balance})
    return out


def transaction_list(entries: list[Entry], chart: Chart, start: date, end: date, *, account: str | None = None,
                     party: str | None = None) -> list[dict]:
    out = []
    for e in sorted(_live(entries), key=lambda e: (e.date, e.id)):
        if not start <= e.date <= end or not _party_match(e, party):
            continue
        codes = list(dict.fromkeys(l.account for l in e.lines))
        if account and account not in codes:
            continue
        out.append({"entry_id": e.id, "date": e.date, "book": e.book, "source": e.source, "reference": e.reference,
                    "party": e.party_name, "particulars": e.particulars, "accounts": codes,
                    "account_names": [chart.name(c) for c in codes], "amount": c2(e.debits()),
                    "ref": entry_ref(e.id)})
    return out


# --- adjusted trial balance and adjusting entries --------------------------------------------------------------------

def is_adjusting(e: Entry, adjusting_ids: set[str]) -> bool:
    return e.id in adjusting_ids or e.source in ADJUSTING_SOURCES


def adjusted_tb(entries: list[Entry], chart: Chart, as_of: date, fye: int, closing_account: str,
                adjusting_ids: set[str]) -> dict:
    """Unadjusted → adjustments → adjusted balances (debit-positive) as of a date; earlier years' P&L is its own row."""
    live = _live(entries)
    start = fy_start(as_of, fye)
    pnl = set(_pnl_codes(chart))
    adjusted = {k: v for k, v in _sums(live, _in(None, as_of)).items() if k not in pnl}
    adjusted.update({k: v for k, v in _sums(live, _in(start, as_of)).items() if k in pnl})
    prior = c2(total(v for k, v in _sums(live, _in(None, start - timedelta(days=1))).items() if k in pnl))
    adjustments = _sums(live, lambda e: start <= e.date <= as_of and is_adjusting(e, adjusting_ids))
    rows = []
    for a in chart.accounts:
        adj, after = adjustments.get(a.code, ZERO), adjusted.get(a.code, ZERO)
        if not adj and not after:
            continue
        window = {"start": start if a.code in pnl else None, "end": as_of}
        rows.append(_row(f"acct:{a.code}", f"{a.code} {a.name}", 0, "account", [a.code],
                         [c2(after - adj), c2(adj), c2(after)], [None, None, window]))
    if prior:
        rows.append(_row("prior_earnings", "Prior years' earnings not yet closed", 0, "account", sorted(pnl),
                         [prior, ZERO, prior], [None, None, {"start": None, "end": start - timedelta(days=1)}]))
    totals = [c2(total(r["values"][i] for r in rows)) for i in range(3)]
    debits = [c2(total(r["values"][i] for r in rows if r["values"][i] > 0)) for i in range(3)]
    rows.append(_row("total", "Total (debits − credits)", 0, "total", [], totals, [None] * 3))
    del closing_account
    columns = [{"key": k, "label": label, "start": start, "end": as_of, "kind": "amount"}
               for k, label in (("unadjusted", "Unadjusted"), ("adjustments", "Adjustments"), ("adjusted", "Adjusted"))]
    return {"columns": columns, "rows": rows, "debit_totals": debits}


def adjusting_entries(entries: list[Entry], chart: Chart, start: date, end: date, adjusting_ids: set[str]) -> list[dict]:
    out = []
    for e in sorted(_live(entries), key=lambda e: (e.date, e.id)):
        if not start <= e.date <= end or not is_adjusting(e, adjusting_ids):
            continue
        kind = "Adjusting journal entry" if e.id in adjusting_ids else ADJUSTING_SOURCES[e.source]
        out.append({"entry_id": e.id, "date": e.date, "book": e.book, "reference": e.reference,
                    "particulars": e.particulars, "kind": kind, "amount": c2(e.debits()), "ref": entry_ref(e.id),
                    "lines": [{"code": l.account, "name": chart.name(l.account), "debit": l.debit,
                               "credit": l.credit} for l in e.lines]})
    return out


# --- invalid journal transactions ------------------------------------------------------------------------------------

PROBLEMS = {
    "unbalanced": "Debits and credits don't agree",
    "too_few_lines": "Fewer than two lines",
    "one_side": "A line has both a debit and a credit, or neither",
    "bad_amount": "An amount isn't a number",
    "missing_account": "The account isn't in the chart",
    "inactive_account": "The account is inactive",
    "engine_error": "The books couldn't post this",
}


def _invalid(entry_id: str, on, reference: str, problem: str, detail: str) -> dict:
    return {"entry_id": entry_id, "date": on, "reference": reference, "problem": problem,
            "label": PROBLEMS[problem], "detail": detail, "ref": entry_ref(entry_id)}


def _account_problem(chart: Chart, code: str) -> tuple[str, str] | None:
    account = chart.get(code)
    if account is None:
        return "missing_account", f"Account {code or '(blank)'}"
    if not account.active:
        return "inactive_account", f"{code} {account.name}"
    return None


def check_entries(entries: list[Entry], chart: Chart) -> list[dict]:
    """Posted entries that don't balance or hit an account that's missing or inactive."""
    out = []
    for e in entries:
        for l in e.lines:
            problem = _account_problem(chart, l.account)
            if problem:
                out.append(_invalid(e.id, e.date, e.reference, problem[0], problem[1]))
        if e.debits() != e.credits():
            out.append(_invalid(e.id, e.date, e.reference, "unbalanced",
                                f"Debits {e.debits():,.2f} · credits {e.credits():,.2f}"))
    return out


def _money(value) -> Decimal | None:
    try:
        amount = Decimal(str(value if value not in (None, "") else "0"))
    except (InvalidOperation, ValueError):
        return None
    return amount if amount.is_finite() else None


def check_manual(rows: list[dict], chart: Chart) -> list[dict]:
    """Typed journal entries as stored (``{id, entry_date, reference, lines}``), checked line by line."""
    out = []
    for row in rows:
        entry_id, on, ref = f"je:{row['id']}", row.get("entry_date"), row.get("reference") or ""
        lines = row.get("lines") or []
        if len(lines) < 2:
            out.append(_invalid(entry_id, on, ref, "too_few_lines", f"{len(lines)} line(s)"))
        debit = credit = ZERO
        for n, line in enumerate(lines, start=1):
            dr, cr = _money(line.get("debit")), _money(line.get("credit"))
            if dr is None or cr is None:
                out.append(_invalid(entry_id, on, ref, "bad_amount", f"Line {n}"))
            elif (dr > 0) == (cr > 0) or dr < 0 or cr < 0:
                out.append(_invalid(entry_id, on, ref, "one_side", f"Line {n}"))
            debit, credit = debit + (dr or ZERO), credit + (cr or ZERO)
            problem = _account_problem(chart, str(line.get("account_code") or ""))
            if problem:
                out.append(_invalid(entry_id, on, ref, problem[0], f"Line {n}: {problem[1]}"))
        if c2(debit) != c2(credit):
            out.append(_invalid(entry_id, on, ref, "unbalanced", f"Debits {debit:,.2f} · credits {credit:,.2f}"))
    return out


# --- drill-down ------------------------------------------------------------------------------------------------------

def postings(entries: list[Entry], chart: Chart, codes: list[str], start: date | None, end: date,
             limit: int = 500) -> dict:
    """The posting lines of ``codes`` in a window (newest last); ``total`` is debit − credit of all of them."""
    wanted = set(codes)
    lines = []
    for e in sorted(_live(entries), key=lambda e: (e.date, e.id)):
        if (start is not None and e.date < start) or e.date > end:
            continue
        for l in e.lines:
            if l.account in wanted:
                lines.append({**_line_out(e, l.debit, l.credit), "code": l.account, "name": chart.name(l.account)})
    amount = c2(total(l["debit"] - l["credit"] for l in lines))
    return {"lines": lines[:limit], "count": len(lines), "total": amount, "truncated": len(lines) > limit}


# --- KPIs ------------------------------------------------------------------------------------------------------------

def _ratio(top: Decimal, bottom: Decimal, pct: bool) -> Decimal | None:
    if bottom == 0:
        return None
    return c2(top / bottom * (100 if pct else 1))


def kpis(pnl: dict, bs: dict, chart: Chart) -> dict:
    """Margins (% of net sales) from the P&L's first column and liquidity ratios from the BS's first column."""
    first = {r["key"]: r["values"][0] for r in pnl["rows"] if r["values"] and r["values"][0] is not None}
    sales = first.get("net_sales", ZERO)
    balances = {r["codes"][0]: r["values"][0] for r in bs["rows"] if r["key"].startswith("acct:")}
    current_assets = quick = current_liab = ZERO
    for code, value in balances.items():
        account = chart.get(code)
        if account is None:
            continue
        key = _key(chart, code)
        if account.type == "asset" and key not in _NON_CURRENT:
            current_assets += value
            if key in _QUICK:
                quick += value
        elif account.type == "liability" and not _is_loan(chart, code):
            current_liab += value
    return {
        "net_sales": sales, "gross_profit": first.get("gross_profit", ZERO), "net_income": first.get("net_income", ZERO),
        "operating_expenses": first.get("opex_total", ZERO),
        "gross_margin": _ratio(first.get("gross_profit", ZERO), sales, True),
        "net_margin": _ratio(first.get("net_income", ZERO), sales, True),
        "opex_ratio": _ratio(first.get("opex_total", ZERO), sales, True),
        "current_assets": c2(current_assets), "quick_assets": c2(quick), "current_liabilities": c2(current_liab),
        "current_ratio": _ratio(current_assets, current_liab, False),
        "quick_ratio": _ratio(quick, current_liab, False),
    }


# --- cash flow -------------------------------------------------------------------------------------------------------

def cash_flow(entries: list[Entry], chart: Chart, start: date, end: date, fye: int, closing_account: str) -> list[dict]:
    """Indirect-method cash flow for a window (opening balances entered inside it count as before it)."""
    live = _live(entries)
    opening_inside = lambda e: start <= e.date <= end and e.source == "opening"  # noqa: E731
    before = _sums(live, lambda e: e.date < start or opening_inside(e))
    moves = _sums(live, lambda e: start <= e.date <= end and e.source != "opening")
    pnl = set(_pnl_codes(chart))
    net_income = c2(-total(v for k, v in moves.items() if k in pnl))
    cash = [a.code for a in chart.accounts if _key(chart, a.code) in _CASH]
    accum = [a.code for a in chart.accounts if _key(chart, a.code) == "accum_dep"]
    depreciation = c2(-total(moves.get(c, ZERO) for c in accum))
    working, investing, financing = [], [], []
    for a in chart.accounts:
        delta = moves.get(a.code, ZERO)
        if a.code in cash or a.code in accum or a.code in pnl or not delta:
            continue
        key = _key(chart, a.code)
        if key == "ppe":
            investing.append({"key": f"inv:{a.code}", "line": f"Acquisition of {a.name.lower()}", "amount": c2(-delta)})
        elif a.type == "equity" or _is_loan(chart, a.code):
            financing.append({"key": f"fin:{a.code}", "line": a.name, "amount": c2(-delta)})
        else:
            label = (f"(Increase) decrease in {a.name.lower()}" if a.type == "asset"
                     else f"Increase (decrease) in {a.name.lower()}")
            working.append({"key": f"op:{a.code}", "line": label, "amount": c2(-delta)})
    operating = c2(net_income + depreciation + total(r["amount"] for r in working))
    inv_total = c2(total(r["amount"] for r in investing))
    fin_total = c2(total(r["amount"] for r in financing))
    cash_open = c2(total(before.get(c, ZERO) for c in cash))
    cash_end = c2(cash_open + total(moves.get(c, ZERO) for c in cash))
    del fye, closing_account

    def r(key, line, amount=None, level=0):
        return {"key": key, "line": line, "amount": amount, "level": level}

    return ([r("op", "Cash flows from operating activities"), r("ni", "Net income (loss)", net_income, 1),
             r("dep", "Depreciation", depreciation, 1)]
            + [{**w, "level": 1} for w in working]
            + [r("op_total", "Net cash from (used in) operating activities", operating),
               r("inv", "Cash flows from investing activities")] + [{**w, "level": 1} for w in investing]
            + [r("inv_total", "Net cash from (used in) investing activities", inv_total),
               r("fin", "Cash flows from financing activities")] + [{**w, "level": 1} for w in financing]
            + [r("fin_total", "Net cash from (used in) financing activities", fin_total),
               r("net", "Net increase (decrease) in cash", c2(operating + inv_total + fin_total)),
               r("cash_open", "Cash, beginning", cash_open), r("cash_end", "Cash, end", cash_end)])
