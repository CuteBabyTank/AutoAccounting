"""Journals, General Ledger, AR/AP subsidiary ledgers and trial balance for a date window (pure).

Rows are keyed dicts, like the other ledger tabs, so versions diff and highlight unchanged.
"""

from datetime import date, timedelta
from decimal import Decimal

from app.services.accounting.books.chart import JOURNAL_BOOKS, Chart
from app.services.accounting.compute.books import Entry
from app.services.accounting.compute.due_dates import quarter_start
from app.services.accounting.compute.money import ZERO, c2, total
from app.services.accounting.matching import normalize_name
from app.services.accounting.periods import period_for

BOOK_TABS = ("SJ", "PJ", "CRJ", "CDJ", "GJ", "GL", "AR", "AP", "TB")


def entry_numbers(entries: list[Entry], fye: int, final: dict[str, str] | None = None) -> dict[str, str]:
    """Entry numbers per book per fiscal year: the final number of a closed month's entry, else provisional
    (``GJ-2026-P0013``), continuing after the closed months' numbers."""
    final = final or {}
    counters: dict[tuple[str, int], int] = {}
    out: dict[str, str] = {}
    for e in entries:
        if e.id in final:
            book, fy, n = final[e.id].rsplit("-", 2)
            key = (book, int(fy))
            counters[key] = max(counters.get(key, 0), int(n))
            out[e.id] = final[e.id]
    for e in entries:
        if e.id in out:
            continue
        fy = period_for(e.date, fye).fiscal_year
        n = counters[(e.book, fy)] = counters.get((e.book, fy), 0) + 1
        out[e.id] = f"{e.book}-{fy}-P{n:04d}"
    return out


def balances(entries: list[Entry], upto: date) -> dict[str, Decimal]:
    out: dict[str, Decimal] = {}
    for e in entries:
        if e.date > upto:
            continue
        for l in e.lines:
            out[l.account] = c2(out.get(l.account, ZERO) + l.debit - l.credit)
    return out


def fiscal_balances(entries: list[Entry], chart: Chart, upto: date, fye: int, closing_account: str, window_start: date | None = None) -> dict[str, Decimal]:
    """Balances with P&L accounts closed into equity (virtual close until phase 3 closing entries).

    P&L accounts (income, cost, expense) from before the fiscal year start are closed into
    closing_account; only current fiscal year P&L activity is shown. Balance-sheet accounts
    carry forward normally.

    When window_start is provided and is the start of the fiscal year after upto, all P&L accounts
    up to upto are closed (since upto is the day before window_start, this means closing the entire
    prior fiscal year).
    """
    fy = period_for(upto, fye).fiscal_year
    fy_start = quarter_start(fy, 1, fye)

    # Check if window_start is a fiscal year start for the period after upto
    # This happens when window_start is the first day of the fiscal year following upto's fiscal year
    next_fy = fy + 1
    next_fy_start = quarter_start(next_fy, 1, fye)
    is_fy_start = window_start and window_start == next_fy_start

    out: dict[str, Decimal] = {}
    prior_pnl: dict[str, Decimal] = {}

    for e in entries:
        if e.date > upto:
            continue
        for l in e.lines:
            acct = chart.get(l.account)
            is_pnl = acct and acct.type in ("income", "cost", "expense")

            if is_pnl and (is_fy_start or e.date < fy_start):
                # Accumulate all P&L separately (either all for fy_start case, or prior for normal case)
                prior_pnl[l.account] = c2(prior_pnl.get(l.account, ZERO) + l.debit - l.credit)
            else:
                # Current year P&L or balance-sheet accounts
                out[l.account] = c2(out.get(l.account, ZERO) + l.debit - l.credit)

    # Close prior P&L into closing account
    if prior_pnl:
        net_prior = total(prior_pnl.values())
        if net_prior != 0:
            out[closing_account] = c2(out.get(closing_account, ZERO) + net_prior)

    return out


def _side(balance: Decimal) -> str:
    return "Dr" if balance > 0 else ("Cr" if balance < 0 else "")


def _net(e: Entry, code: str, debit_side: bool) -> Decimal:
    value = total(l.debit - l.credit for l in e.lines if l.account == code)
    return value if debit_side else c2(-value)


def _base(e: Entry, numbers: dict[str, str]) -> dict:
    return {"key": e.id, "date": e.date.isoformat(), "entry_no": numbers[e.id], "reference": e.reference,
            "party": e.party_name, "tin": e.party_tin, "particulars": e.particulars}


def _columnar(e: Entry, numbers, chart: Chart, columns: dict[str, tuple[str, bool]]) -> list[dict]:
    """One row per entry with the named columns; a line goes to its account's column only when it is on the
    column's side (Dr column: a debit, Cr column: a credit). Every other line goes to Sundry (extra rows if several)."""
    row = _base(e, numbers)
    for name in columns:
        row[name] = ZERO
    sundry = []
    for l in e.lines:
        name = next((n for n, (code, debit_side) in columns.items()
                     if code == l.account and (l.debit > 0 if debit_side else l.credit > 0)), None)
        if name is None:
            sundry.append(l)
        else:
            row[name] = c2(row[name] + (l.debit if columns[name][1] else l.credit))
    rows = [row]
    for i, l in enumerate(sundry or [None]):
        target = row if i == 0 else {**{k: "" for k in row}, **{name: ZERO for name in columns},
                                    "key": f"{e.id}#{i}", "date": row["date"], "entry_no": row["entry_no"]}
        target["sundry_account"] = f"{l.account} {chart.name(l.account)}" if l else ""
        target["sundry_dr"] = l.debit if l else ZERO
        target["sundry_cr"] = l.credit if l else ZERO
        if i:
            rows.append(target)
    return rows


def _journal(book: str, window: list[Entry], numbers, chart: Chart) -> list[dict]:
    code = chart.code
    rows: list[dict] = []
    for e in window:
        if e.book != book:
            continue
        if book == "SJ":
            row = _base(e, numbers)
            row.update(ar=_net(e, code("ar"), True), vatable=e.get("vatable"), zero_rated=e.get("zero_rated"),
                       exempt=e.get("exempt"), output_vat=_net(e, code("output_vat"), False))
            rows.append(row)
        elif book == "PJ":
            row = _base(e, numbers)
            special = {code("input_vat"), code("ewt_payable"), code("ap")}
            debits = [l for l in e.lines if l.account not in special]
            row.update(account=", ".join(f"{l.account} {chart.name(l.account)}" for l in debits),
                       expense=total(l.debit - l.credit for l in debits),
                       input_vat=_net(e, code("input_vat"), True), ewt=_net(e, code("ewt_payable"), False),
                       ap=_net(e, code("ap"), False))
            rows.append(row)
        elif book == "CRJ":
            rows += _columnar(e, numbers, chart, {"cash": (code("cash"), True), "bank": (code("bank"), True),
                                                  "cwt": (code("cwt"), True), "ar": (code("ar"), False)})
        elif book == "CDJ":
            rows += _columnar(e, numbers, chart, {"cash": (code("cash"), False), "bank": (code("bank"), False),
                                                  "ap": (code("ap"), True), "input_vat": (code("input_vat"), True),
                                                  "ewt": (code("ewt_payable"), False)})
        else:  # GJ: one row per line
            for i, l in enumerate(e.lines):
                rows.append({"key": f"{e.id}#{i}", "date": e.date.isoformat(), "entry_no": numbers[e.id],
                             "code": l.account, "account": chart.name(l.account),
                             "particulars": " ".join(x for x in (e.particulars, e.reference) if x),
                             "debit": l.debit, "credit": l.credit})
    return rows


def _gl(entries, window, window_start, chart, numbers, fye, closing_account) -> list[dict]:
    # Use brought-forward balances from day before window_start
    bf_date = window_start - timedelta(days=1)
    before = {code: bal for code, bal in fiscal_balances(entries, chart, bf_date, fye, closing_account, window_start).items() if bal != 0}
    activity: dict[str, list] = {}
    for e in window:
        for i, l in enumerate(e.lines):
            activity.setdefault(l.account, []).append((e, i, l))
    rows: list[dict] = []
    for code in sorted(set(before) | set(activity)):
        bal = before.get(code, ZERO)
        common = {"code": code, "account": chart.name(code)}
        rows.append({"key": f"{code}|bf", **common, "date": window_start.isoformat(), "reference": "",
                     "particulars": "Balance brought forward", "debit": ZERO, "credit": ZERO,
                     "balance": abs(bal), "side": _side(bal)})
        for e, i, l in activity.get(code, []):
            bal = c2(bal + l.debit - l.credit)
            rows.append({"key": f"{code}|{e.id}#{i}", **common, "date": e.date.isoformat(),
                         "reference": numbers[e.id], "particulars": " ".join(x for x in (e.particulars, e.reference) if x),
                         "debit": l.debit, "credit": l.credit, "balance": abs(bal), "side": _side(bal)})
    return rows


def _party(e: Entry, l) -> tuple[str, str, str]:
    name, tin = (l.party_name, l.party_tin) if (l.party_name or l.party_tin) else (e.party_name, e.party_tin)
    return (tin or f"NAME:{normalize_name(name)}"), name, tin


def _subledger(entries, window, window_start, code: str, numbers) -> list[dict]:
    # Build a map of normalized-name → TIN from all entries with both name and TIN
    name_to_tin: dict[str, str] = {}
    for e in entries:
        for l in e.lines:
            if l.account == code:
                _, name, tin = _party(e, l)
                if name and tin:
                    normalized = normalize_name(name)
                    if normalized in name_to_tin:
                        # Only consolidate if they map to the same TIN
                        if name_to_tin[normalized] != tin:
                            # Multiple TINs for same name: skip consolidation
                            name_to_tin[normalized] = None
                    else:
                        name_to_tin[normalized] = tin

    # Filter out normalized names with None (multiple TINs)
    name_to_tin = {k: v for k, v in name_to_tin.items() if v is not None}

    opening: dict[str, list] = {}
    for e in entries:
        if e.date >= window_start:
            continue
        for l in e.lines:
            if l.account == code:
                key, name, tin = _party(e, l)
                # If this is a NAME-based key, check if it should be consolidated
                if key.startswith("NAME:") and not tin:
                    normalized = key[5:]  # Strip "NAME:" prefix
                    if normalized in name_to_tin and name_to_tin[normalized]:
                        key = name_to_tin[normalized]
                        tin = key
                slot = opening.setdefault(key, [name, tin, ZERO])
                slot[2] = c2(slot[2] + l.debit - l.credit)

    activity: dict[str, list] = {}
    for e in window:
        for i, l in enumerate(e.lines):
            if l.account == code:
                key, name, tin = _party(e, l)
                # If this is a NAME-based key, check if it should be consolidated
                if key.startswith("NAME:") and not tin:
                    normalized = key[5:]  # Strip "NAME:" prefix
                    if normalized in name_to_tin and name_to_tin[normalized]:
                        key = name_to_tin[normalized]
                        tin = key
                activity.setdefault(key, []).append((e, i, l, name, tin))

    rows: list[dict] = []
    # Sort by (lowercase name, key) for determinism
    def sort_key(k):
        name_val = (opening.get(k) or activity[k][0][3:])[0].lower()
        return (name_val, k)

    for key in sorted(set(opening) | set(activity), key=sort_key):
        name, tin, bal = opening.get(key) or [activity[key][0][3], activity[key][0][4], ZERO]
        if bal != 0:
            rows.append({"key": f"{key}|bf", "party": name, "tin": tin, "date": window_start.isoformat(),
                         "reference": "", "particulars": "Balance brought forward", "debit": ZERO, "credit": ZERO,
                         "balance": abs(bal), "side": _side(bal)})
        for e, i, l, _, _ in activity.get(key, []):
            bal = c2(bal + l.debit - l.credit)
            rows.append({"key": f"{key}|{e.id}#{i}", "party": name, "tin": tin, "date": e.date.isoformat(),
                         "reference": numbers[e.id], "particulars": e.particulars, "debit": l.debit,
                         "credit": l.credit, "balance": abs(bal), "side": _side(bal)})
    return rows


def _tb(entries, window_end, chart, fye, closing_account) -> list[dict]:
    rows = [{"key": code, "code": code, "account": chart.name(code),
             "debit": bal if bal > 0 else ZERO, "credit": -bal if bal < 0 else ZERO}
            for code, bal in sorted(fiscal_balances(entries, chart, window_end, fye, closing_account).items()) if bal != 0]
    rows.append({"key": "~total", "code": "", "account": "Total", "debit": total(r["debit"] for r in rows),
                 "credit": total(r["credit"] for r in rows)})
    return rows


def trial_balance_totals(rows: list[dict]) -> tuple[Decimal, Decimal]:
    last = rows[-1] if rows else {"debit": ZERO, "credit": ZERO}
    return last["debit"], last["credit"]


def build_books(entries: list[Entry], chart: Chart, window_start: date, window_end: date, fye: int,
                books_kept: frozenset[str], closing_account: str,
                tb_entries: list[Entry] | None = None, final: dict[str, str] | None = None) -> dict[str, list[dict]]:
    """``tb_entries`` (the entries without year-end closing) gives the adjusted trial balance at fiscal year end;
    ``final`` holds closed months' entry numbers."""
    numbers = entry_numbers(entries, fye, final)
    window = [e for e in entries if window_start <= e.date <= window_end]
    tabs: dict[str, list[dict]] = {}
    for book in JOURNAL_BOOKS:
        if book == "GJ" or book in books_kept:
            tabs[book] = _journal(book, window, numbers, chart)
    tabs["GL"] = _gl(entries, window, window_start, chart, numbers, fye, closing_account)
    tabs["AR"] = _subledger(entries, window, window_start, chart.code("ar"), numbers)
    tabs["AP"] = _subledger(entries, window, window_start, chart.code("ap"), numbers)
    tabs["TB"] = _tb(entries if tb_entries is None else tb_entries, window_end, chart, fye, closing_account)
    return tabs
