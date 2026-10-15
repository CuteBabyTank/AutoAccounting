"""Books of accounts: post documents, payments, taxes, depreciation and typed entries (pure).

Accrual basis, periodic inventory. Amounts come from the returns engine (cost_base, claims_input_vat,
computed EWT, depreciation_between) so the books and the returns agree.
"""

import calendar
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.services.accounting.books.chart import Chart, JOURNAL_BOOKS
from app.services.accounting.compute.cogs import claims_input_vat, cost_base, is_capital_goods
from app.services.accounting.compute.depreciation import Asset, depreciation_between
from app.services.accounting.compute.inputs import CompanyFacts, DocLine
from app.services.accounting.compute.money import ZERO, c2, total

CASH_KEYS = {"cash": "cash", "bank": "bank", "ewallet": "ewallet"}
_OVERPAY = Decimal("1.00")


@dataclass(frozen=True)
class Line:
    account: str
    debit: Decimal = ZERO
    credit: Decimal = ZERO
    party_name: str = ""
    party_tin: str = ""


@dataclass(frozen=True)
class Entry:
    id: str
    date: date
    book: str
    reference: str
    party_name: str
    party_tin: str
    particulars: str
    source: str                       # document | payment | tax | depreciation | manual | opening
    lines: tuple[Line, ...]
    meta: tuple[tuple[str, Decimal], ...] = ()

    def debits(self) -> Decimal:
        return total(l.debit for l in self.lines)

    def credits(self) -> Decimal:
        return total(l.credit for l in self.lines)

    def get(self, key: str) -> Decimal:
        return dict(self.meta).get(key, ZERO)


@dataclass(frozen=True)
class Payment:
    id: str
    settles: str               # DocLine.id of the invoice / bill / payroll paid
    on: date
    amount: Decimal | None     # None = whatever is still open
    via: str                   # cash | bank | ewallet
    ref: str


@dataclass(frozen=True)
class ManualEntry:
    id: str
    kind: str                  # opening | manual
    book: str
    on: date
    reference: str
    particulars: str
    lines: tuple[Line, ...]


@dataclass(frozen=True)
class QuarterTaxes:
    year: int
    quarter: int
    end: date
    forms: dict
    ending_inventory: Decimal | None = None     # the quarter's count: the books' inventory is set to it
    # (month end, employee share, employer share) of SSS / PhilHealth / Pag-IBIG, from the payroll inputs
    contributions: tuple[tuple[date, Decimal, Decimal], ...] = ()


@dataclass(frozen=True)
class AnnualTaxes:
    """The annual income tax return a fiscal year closes with (the filed version, else the latest)."""

    year: int
    end: date
    form: str                                   # 1702RT | 1701 | 1701A
    forms: dict


@dataclass(frozen=True)
class FiledPayment:
    form: str
    year: int
    quarter: int
    on: date
    amount: Decimal


@dataclass(frozen=True)
class BooksInput:
    company: CompanyFacts
    chart: Chart
    books_kept: frozenset[str]
    start: date
    through: date
    lines: tuple[DocLine, ...] = ()
    ewt: dict[str, Decimal] = field(default_factory=dict)
    payments: tuple[Payment, ...] = ()
    manual: tuple[ManualEntry, ...] = ()
    quarters: tuple[QuarterTaxes, ...] = ()
    filed: tuple[FiledPayment, ...] = ()
    assets: tuple[Asset, ...] = ()
    annual: tuple[AnnualTaxes, ...] = ()


def _dr(account: str, amount) -> Line | None:
    amount = c2(amount)
    if amount > 0:
        return Line(account, debit=amount)
    if amount < 0:
        return Line(account, credit=-amount)
    return None


def _cr(account: str, amount) -> Line | None:
    return _dr(account, -c2(amount))


def make_entry(id: str, on: date, book: str, reference: str, party: tuple[str, str], particulars: str, source: str,
               *lines: Line | None, meta: tuple[tuple[str, Decimal], ...] = ()) -> Entry | None:
    kept = tuple(l for l in lines if l is not None)
    if not kept:
        return None
    entry = Entry(id, on, book, reference, party[0], party[1], particulars, source, kept, meta)
    if entry.debits() != entry.credits():
        raise ValueError(f"Unbalanced journal entry {id}: debits {entry.debits()} ≠ credits {entry.credits()}")
    return entry


def _book(inp: BooksInput, wanted: str) -> str:
    return wanted if wanted in inp.books_kept else "GJ"


def _party(l: DocLine) -> tuple[str, str]:
    return l.counterparty_name, l.counterparty_tin


def _kept(*entries: Entry | None) -> list[Entry]:
    return [e for e in entries if e is not None]


def document_entries(l: DocLine, inp: BooksInput) -> list[Entry]:
    """The entry a document posts on its own date (none for 2307s issued, support or unsorted papers)."""
    chart, vat = inp.chart, inp.company.vat_registered
    party, ref, name = _party(l), l.doc_number, l.counterparty_name
    if l.category == "sales" and l.client_role == "seller":
        sales = chart.code("sales" if l.gross >= 0 else "sales_returns")
        return _kept(make_entry(
            f"doc:{l.id}:sale", l.doc_date, _book(inp, "SJ"), ref, party, f"Sale to {name}".strip(), "document",
            _dr(chart.code("ar"), l.gross), _cr(sales, l.gross - l.vat), _cr(chart.code("output_vat"), l.vat),
            meta=(("vatable", l.vatable), ("zero_rated", l.zero_rated), ("exempt", l.exempt)),
        ))
    if l.category in ("purchases", "expenses") and l.client_role == "buyer":
        account = chart.code("ppe") if is_capital_goods(l) else chart.doc_account(l.account, l.gl_account)
        input_vat = l.vat if claims_input_vat(l, vat) else ZERO
        ewt = inp.ewt.get(l.id, ZERO)
        return _kept(make_entry(
            f"doc:{l.id}:buy", l.doc_date, _book(inp, "PJ"), ref, party, f"{chart.name(account)}, {name}".strip(", "),
            "document", _dr(account, cost_base(l, vat)), _dr(chart.code("input_vat"), input_vat),
            _cr(chart.code("ewt_payable"), ewt), _cr(chart.code("ap"), l.gross - ewt),
        ))
    if l.category == "payroll":
        return _kept(make_entry(
            f"doc:{l.id}:payroll", l.doc_date, "GJ", ref, party, "Payroll", "document",
            _dr(chart.doc_account("salaries", l.gl_account), l.gross), _cr(chart.code("wtc_payable"), l.withholding),
            _cr(chart.code("salaries_payable"), l.gross - l.withholding),
        ))
    if l.category == "2307" and l.client_role == "seller":
        return _kept(make_entry(
            f"doc:{l.id}:2307", l.doc_date, "GJ", ref, party, f"BIR 2307 from {name}".strip(), "document",
            _dr(chart.code("cwt"), l.withholding), _cr(chart.code("ar"), l.withholding),
        ))
    return []


def amount_due(l: DocLine, inp: BooksInput, contributions: dict[str, Decimal] | None = None) -> Decimal:
    """What the counterparty pays / is paid in cash: net of tax withheld (and, for payroll, the employees'
    SSS / PhilHealth / Pag-IBIG share deducted from their pay)."""
    if l.category == "sales":
        return c2(l.gross - l.withholding)
    if l.category in ("purchases", "expenses"):
        return c2(l.gross - inp.ewt.get(l.id, ZERO))
    if l.category == "payroll":
        return c2(l.gross - l.withholding - (contributions or {}).get(l.id, ZERO))
    return ZERO


def _month_contributions(inp: BooksInput) -> dict[tuple[int, int], tuple[date, Decimal, Decimal]]:
    out: dict[tuple[int, int], tuple[date, Decimal, Decimal]] = {}
    for q in inp.quarters:
        for on, employee, employer in q.contributions:
            if (employee > 0 or employer > 0) and inp.start <= on <= inp.through:
                out[(on.year, on.month)] = (on, c2(employee), c2(employer))
    return out


def employee_contributions(inp: BooksInput) -> tuple[dict[str, Decimal], list[tuple[int, int]]]:
    """Each payroll document's part of its month's employee share (by gross pay), and the months with
    contributions but no payroll document to take them from."""
    by_doc: dict[str, Decimal] = {}
    orphans: list[tuple[int, int]] = []
    for key, (_, employee, _) in sorted(_month_contributions(inp).items()):
        docs = sorted((l for l in inp.lines if l.category == "payroll" and l.doc_date is not None
                       and (l.doc_date.year, l.doc_date.month) == key), key=lambda l: (l.doc_date, l.id))
        gross = total(l.gross for l in docs)
        if not docs or gross <= 0:
            if employee > 0:
                orphans.append(key)
            continue
        left = employee
        for index, l in enumerate(docs):
            part = left if index == len(docs) - 1 else c2(employee * l.gross / gross)
            by_doc[l.id] = part
            left = c2(left - part)
    return by_doc, orphans


def payment_entries(inp: BooksInput, warnings: list[str]) -> list[Entry]:
    chart = inp.chart
    by_id = {l.id: l for l in inp.lines}
    remaining: dict[str, Decimal] = {}
    out: list[Entry] = []
    unknown = over = fully_withheld = 0
    contributions, _ = employee_contributions(inp)
    for p in sorted(inp.payments, key=lambda p: (p.on, p.id)):
        l = by_id.get(p.settles)
        if l is None:
            unknown += 1
            continue
        if amount_due(l, inp, contributions) == 0:
            fully_withheld += 1
            continue
        if p.on > inp.through:
            continue
        left = remaining.setdefault(l.id, amount_due(l, inp, contributions))
        amount = c2(p.amount) if p.amount is not None else max(left, ZERO)
        remaining[l.id] = c2(left - amount)
        if p.on < inp.start or amount == 0:  # before the books: the opening balance already reflects it
            continue
        if amount > left + _OVERPAY:
            over += 1
        cash = chart.code(CASH_KEYS.get(p.via, "cash"))
        party, ref = _party(l), p.ref or l.doc_number
        if l.category == "sales":
            entry = make_entry(f"pay:{p.id}", p.on, _book(inp, "CRJ"), ref, party,
                               f"Collection of {l.doc_number}".strip(), "payment",
                               _dr(cash, amount), _cr(chart.code("ar"), amount))
        else:
            payable = chart.code("salaries_payable" if l.category == "payroll" else "ap")
            entry = make_entry(f"pay:{p.id}", p.on, _book(inp, "CDJ"), ref, party,
                               f"Payment of {l.doc_number}".strip(), "payment",
                               _dr(payable, amount), _cr(cash, amount))
        out += _kept(entry)
    if unknown:
        warnings.append(f"{unknown} payment(s) point to a document that isn't in the books (deleted, excluded, or "
                        "not a sale, purchase, expense or payroll); they were left out.")
    if fully_withheld:
        warnings.append(f"{fully_withheld} payment(s) are for documents with nothing left to pay (fully withheld); "
                        "they were left out.")
    if over:
        warnings.append(f"{over} payment(s) are more than the balance left on their document; the excess stays in "
                        "receivables / payables as an advance.")
    return out


_PAID_ACCOUNT = (("2550Q", "vat_payable"), ("2551Q", "pt_payable"), ("0619E", "ewt_payable"),
                 ("1601EQ", "ewt_payable"), ("1601C", "wtc_payable"), ("1701Q", "it_payable"),
                 ("1702Q", "it_payable"), ("1702RT", "it_payable"), ("1701A", "it_payable"), ("1701", "it_payable"))
# Annual return: (tax due, CWT of the 4th quarter, excess MCIT applied, credits that stand in for Q1–Q3's tax due)
_ANNUAL_ITEMS = {
    "1702RT": ("43", "49", "47", ("45", "46", "48")),
    "1701": ("P6_5", "P7_4", None, ("P7_2", "P7_3")),
    "1701A": ("20", "60", None, ("58", "59")),
}
_NO_PARTY = ("", "")


def _num(forms: dict, form: str, item: str) -> Decimal:
    value = forms.get(form, {}).get(item)
    return c2(value) if value not in (None, "") else ZERO


def _income_tax(forms: dict) -> tuple[Decimal, Decimal, Decimal] | None:
    """(tax due year to date, CWT credited this quarter, baseline: tax paid + CWT of earlier quarters) from a quarterly
    ITR. Prior-year excess credits stay out of the baseline: they're last year's overpayment, not this year's expense."""
    if "1702Q" in forms:
        due = _num(forms, "1702Q", "14")
        cwt = _num(forms, "1702Q", "S4_5")
        baseline = _num(forms, "1702Q", "S4_2") + _num(forms, "1702Q", "S4_3") + _num(forms, "1702Q", "S4_4")
        return due, cwt, baseline
    if "1701Q" in forms:
        due_field = "54" if "54" in forms["1701Q"] else "46"
        due = _num(forms, "1701Q", due_field)
        cwt = _num(forms, "1701Q", "58")
        baseline = _num(forms, "1701Q", "56") + _num(forms, "1701Q", "57")
        return due, cwt, baseline
    return None


def _paid_account(form: str) -> str | None:
    return next((key for prefix, key in _PAID_ACCOUNT if form.startswith(prefix)), None)


def tax_entries(inp: BooksInput) -> list[Entry]:
    """Quarter-end VAT / percentage tax / income tax accruals and the payments of filed returns."""
    code = inp.chart.code
    out: list[Entry] = []
    due_so_far: dict[int, Decimal] = {}
    for q in sorted(inp.quarters, key=lambda q: (q.year, q.quarter)):
        f, tag = q.forms, f"{q.year}Q{q.quarter}"
        income = _income_tax(f)
        previous = due_so_far.get(q.year)
        if income is not None:
            due_so_far[q.year] = income[0]
        if not inp.start <= q.end <= inp.through:
            continue
        if "2550Q" in f:  # VAT withheld by government buyers (item 16) is credited from the 2307s' CWT
            output = _num(f, "2550Q", "37B")
            noncreditable, withheld = _num(f, "2550Q", "57B"), _num(f, "2550Q", "16")
            if output > 0:
                net_input = _num(f, "2550Q", "60B")
                applied = min(net_input, output)
                payable = output - applied
                out += _kept(make_entry(
                    f"tax:2550Q:{tag}:close", q.end, "GJ", f"2550-Q {tag}", _NO_PARTY, "VAT for the quarter", "tax",
                    _dr(code("output_vat"), output), _cr(code("input_vat"), applied),
                    _cr(code("vat_payable"), payable),
                    _dr(code("input_vat_expense"), noncreditable), _cr(code("input_vat"), noncreditable),
                    _dr(code("vat_payable"), withheld), _cr(code("cwt"), withheld),
                ))
            else:
                out += _kept(make_entry(
                    f"tax:2550Q:{tag}:close", q.end, "GJ", f"2550-Q {tag}", _NO_PARTY, "VAT for the quarter", "tax",
                    _dr(code("input_vat_expense"), noncreditable), _cr(code("input_vat"), noncreditable),
                    _dr(code("vat_payable"), withheld), _cr(code("cwt"), withheld),
                ))
        if "2551Q" in f:
            due, withheld = _num(f, "2551Q", "14"), _num(f, "2551Q", "15")
            out += _kept(make_entry(
                f"tax:2551Q:{tag}:accrue", q.end, "GJ", f"2551-Q {tag}", _NO_PARTY, "Percentage tax for the quarter",
                "tax", _dr(code("pt_expense"), due), _cr(code("pt_payable"), due),
                _dr(code("pt_payable"), withheld), _cr(code("cwt"), withheld),
            ))
        if income is not None:
            due_ytd, cwt, paid_before = income
            baseline = previous if previous is not None else (paid_before if q.quarter > 1 else ZERO)
            increase = c2(due_ytd - baseline)
            out += _kept(make_entry(
                f"tax:ITQ:{tag}:accrue", q.end, "GJ", f"ITR {tag}", _NO_PARTY, "Income tax for the quarter", "tax",
                _dr(code("income_tax"), increase), _cr(code("it_payable"), increase),
                _dr(code("it_payable"), cwt), _cr(code("cwt"), cwt),
            ))
    for a in sorted(inp.annual, key=lambda a: a.year):
        if a.form not in _ANNUAL_ITEMS or not inp.start <= a.end <= inp.through:
            continue
        f = {a.form: a.forms.get(a.form, {})}
        due_item, cwt_item, mcit_item, base_items = _ANNUAL_ITEMS[a.form]
        due = _num(f, a.form, due_item)
        if a.form == "1701":  # a mixed-income earner's salary tax was withheld by the employer, not a business cost
            due = c2(due - _num(f, a.form, "P7_5"))
        baseline = due_so_far[a.year] if a.year in due_so_far else total(_num(f, a.form, k) for k in base_items)
        excess_mcit = _num(f, a.form, mcit_item) if mcit_item else ZERO
        cwt = _num(f, a.form, cwt_item)
        out += _kept(make_entry(
            f"tax:ITA:{a.year}:accrue", a.end, "GJ", f"{a.form} FY {a.year}", _NO_PARTY,
            "Income tax for the 4th quarter (annual return)", "tax",
            _dr(code("income_tax"), due - baseline), _cr(code("it_payable"), due - baseline),
            _dr(code("it_payable"), cwt), _cr(code("cwt"), cwt),
            _dr(code("it_payable"), excess_mcit), _cr(code("income_tax"), excess_mcit),
        ))
    for p in inp.filed:
        account = _paid_account(p.form)
        if account is None or p.amount <= 0 or not inp.start <= p.on <= inp.through:
            continue
        period = f"FY {p.year}" if p.quarter == 0 else f"{p.year} Q{p.quarter}"
        out += _kept(make_entry(
            f"tax:{p.form}:{p.year}Q{p.quarter}:paid", p.on, _book(inp, "CDJ"), p.form, ("Bureau of Internal Revenue", ""),
            f"Payment of BIR {p.form} for {period}", "tax",
            _dr(code(account), p.amount), _cr(code("bank"), p.amount),
        ))
    return out


def _months(start: date, through: date):
    y, m = start.year, start.month
    while date(y, m, 1) <= through:
        yield date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def depreciation_entries(inp: BooksInput) -> list[Entry]:
    code = inp.chart.code
    out: list[Entry] = []
    for a in inp.assets:
        for first, last in _months(inp.start, inp.through):
            if last > inp.through:
                continue
            amount = depreciation_between(a, first, last)
            out += _kept(make_entry(
                f"dep:{a.id}:{first:%Y-%m}", last, "GJ", a.doc_number, _NO_PARTY, f"Depreciation, {a.description}",
                "depreciation", _dr(code("depreciation"), amount), _cr(code("accum_dep"), amount),
            ))
    return out


def contribution_entries(inp: BooksInput, warnings: list[str]) -> list[Entry]:
    """Each month's SSS / PhilHealth / Pag-IBIG: the employees' share comes out of salaries payable, the
    employer's share is an expense, and both are owed to the agencies until remitted."""
    code = inp.chart.code
    out: list[Entry] = []
    for (year, month), (on, employee, employer) in sorted(_month_contributions(inp).items()):
        out += _kept(make_entry(
            f"contrib:{year}-{month:02d}", on, "GJ", f"Contributions {year}-{month:02d}", _NO_PARTY,
            "SSS / PhilHealth / Pag-IBIG for the month", "payroll",
            _dr(code("salaries_payable"), employee), _dr(code("contributions_expense"), employer),
            _cr(code("contributions_payable"), employee + employer),
        ))
    _, orphans = employee_contributions(inp)
    if orphans:
        months = ", ".join(f"{y}-{m:02d}" for y, m in orphans)
        warnings.append(f"Employee contributions are entered for {months} but there's no payroll document that month "
                        "to deduct them from; salaries payable shows a debit until it's filed.")
    return out


def inventory_entries(inp: BooksInput, posted: list[Entry], warnings: list[str]) -> list[Entry]:
    """Periodic inventory: at each quarter end the inventory account is set to the count, and the change goes
    to cost of sales, so the books' cost of sales is beginning + purchases − ending like the returns'."""
    if inp.company.business_type == "services":
        return []
    code = inp.chart.code
    inventory = code("inventory")
    out: list[Entry] = []
    uncounted: list[str] = []
    for q in sorted(inp.quarters, key=lambda q: (q.year, q.quarter)):
        if not inp.start <= q.end <= inp.through:
            continue
        if q.ending_inventory is None:
            uncounted.append(f"{q.year} Q{q.quarter}")
            continue
        book = c2(sum((l.debit - l.credit for e in posted + out if e.date <= q.end for l in e.lines
                       if l.account == inventory), ZERO))
        change = c2(q.ending_inventory - book)
        out += _kept(make_entry(
            f"inv:{q.year}Q{q.quarter}", q.end, "GJ", f"Inventory count {q.year}Q{q.quarter}", _NO_PARTY,
            "Ending inventory per count; the change goes to cost of sales", "inventory",
            _dr(inventory, change), _cr(code("cogs"), change),
        ))
    if uncounted:
        warnings.append(f"No ending inventory for {', '.join(uncounted)}, so the books leave inventory unchanged and "
                        "count every purchase as cost of sales. Enter the count in the quarter inputs.")
    return out


def manual_entries(inp: BooksInput) -> list[Entry]:
    out: list[Entry] = []
    for m in inp.manual:
        if not inp.start <= m.on <= inp.through:
            continue
        first = m.lines[0] if m.lines else Line("")
        out += _kept(make_entry(f"je:{m.id}", m.on, _book(inp, m.book), m.reference, (first.party_name, first.party_tin),
                                m.particulars, m.kind, *m.lines))
    return out


def post_all(inp: BooksInput) -> tuple[list[Entry], list[str]]:
    """Every entry from the books' start to ``through``, in posting order, plus warnings."""
    warnings: list[str] = []
    entries: list[Entry] = []
    for l in inp.lines:
        if l.doc_date is not None and inp.start <= l.doc_date <= inp.through:
            entries += document_entries(l, inp)
    entries += payment_entries(inp, warnings)
    entries += tax_entries(inp)
    entries += depreciation_entries(inp)
    entries += manual_entries(inp)
    entries += contribution_entries(inp, warnings)
    entries += inventory_entries(inp, entries, warnings)
    entries.sort(key=lambda e: (e.date, JOURNAL_BOOKS.index(e.book) if e.book in JOURNAL_BOOKS else 9, e.id))
    return entries, warnings
