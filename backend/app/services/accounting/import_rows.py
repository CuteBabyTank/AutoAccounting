"""The three importers' row builders (pure): opening trial balance, opening open items, journal entries.

Each takes the sheet (headers + rows as text), the person's column choices, and returns drafts plus everything the
preview shows: the account mapping table (one row per distinct account in the file), row / entry errors, warnings
and whether it is ready to post. Nothing here touches the database; the router re-runs the same build on confirm.
"""

import re
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from app.services.accounting.importing import (
    DATE_LABELS, AccountMatch, AccountRef, detect_date_format, match_account, norm_name, parse_amount, parse_date,
    source_key,
)

ZERO = Decimal("0")
MAX_ENTRIES = 500
MAX_LINES = 200
MAX_OPEN_ITEMS = 2000

TB_FIELDS = {"account_code": "Account code", "account_name": "Account name", "debit": "Debit", "credit": "Credit",
             "balance": "Balance (signed: + debit, − credit)", "as_of": "As-of date"}
TB_SYNONYMS = (
    (r"code|acct ?no|account ?no|account ?#|^no$|^gl$", "account_code"),
    (r"title|account|name|description|particulars", "account_name"),
    (r"debit|^dr$", "debit"), (r"credit|^cr$", "credit"), (r"balance|amount|net", "balance"),
    (r"as ?of|date|period", "as_of"),
)
OPEN_FIELDS = {"kind": "Type (AR / AP)", "contact_name": "Customer / supplier", "contact_tin": "TIN",
               "doc_number": "Invoice / bill no.", "doc_date": "Invoice date", "due_date": "Due date",
               "terms_days": "Terms (days)", "amount": "Amount still open"}
OPEN_SYNONYMS = (
    (r"^type$|kind|^ar ?/ ?ap$|side", "kind"), (r"tin|tax ?id", "contact_tin"),
    (r"customer|supplier|vendor|client|payee|party|contact|name", "contact_name"),
    (r"due", "due_date"), (r"term", "terms_days"),
    (r"invoice ?(no|number|#)|bill ?(no|number|#)|doc(ument)? ?(no|number|#)|ref|^no$|number", "doc_number"),
    (r"date", "doc_date"), (r"open|balance|amount|outstanding|unpaid", "amount"),
)
JE_FIELDS = {"journal_no": "Journal no.", "date": "Date", "account_code": "Account code",
             "account_name": "Account name", "debit": "Debit", "credit": "Credit",
             "amount": "Amount (signed: + debit, − credit)", "description": "Description / particulars",
             "reference": "Reference", "party_name": "Party name", "party_tin": "Party TIN",
             "adjusting": "Adjusting entry (yes / no)"}
JE_SYNONYMS = (
    (r"adjust|^aje$|^adj$", "adjusting"),
    (r"journal|^je( ?(no|#|number))?$|entry ?(no|#|number)|voucher|batch", "journal_no"),
    (r"party ?tin|^tin$", "party_tin"),
    (r"party|payee|customer|supplier|vendor|name of", "party_name"),
    (r"code|acct ?no|account ?no|account ?#|^gl$", "account_code"),
    (r"account|title", "account_name"), (r"date", "date"), (r"debit|^dr$", "debit"), (r"credit|^cr$", "credit"),
    (r"amount|net", "amount"), (r"desc|particular|memo|narration|explanation|remarks", "description"),
    (r"ref|doc(ument)? ?(no|#)", "reference"),
)

TEMPLATES: dict[str, tuple[list[str], list[list[str]]]] = {
    "opening-tb": (["Account code", "Account name", "Debit", "Credit", "As of"], [
        ["1020", "Cash in bank", "250000.00", "", "2025-12-31"],
        ["1100", "Accounts receivable - trade", "150000.00", "", "2025-12-31"],
        ["2010", "Accounts payable - trade", "", "80000.00", "2025-12-31"],
        ["3010", "Capital", "", "320000.00", "2025-12-31"],
    ]),
    "open-items": (["Type", "Customer / supplier", "TIN", "Invoice no.", "Invoice date", "Due date", "Terms (days)",
                    "Amount still open"], [
        ["AR", "Mabuhay Builders Inc.", "123-456-789-000", "0003", "2025-12-10", "", "30", "150000.00"],
        ["AP", "Pacific Steel Trading", "987-654-321-000", "PS-0077", "2025-12-20", "2026-01-19", "", "80000.00"],
    ]),
    "journal-entries": (["Journal no.", "Date", "Account code", "Account name", "Debit", "Credit", "Description",
                         "Reference", "Party name", "Party TIN", "Adjusting"], [
        ["1", "2026-01-31", "6010", "Salaries and wages", "120000.00", "", "January payroll", "PR-01", "", "", ""],
        ["1", "2026-01-31", "2140", "Withholding tax on compensation payable", "", "8000.00", "", "PR-01", "", "",
         ""],
        ["1", "2026-01-31", "1020", "Cash in bank", "", "112000.00", "", "PR-01", "", "", ""],
        ["2", "2026-01-31", "6100", "Depreciation", "1500.00", "", "January depreciation", "", "", "", "yes"],
        ["2", "2026-01-31", "1510", "Accumulated depreciation", "-1500.00", "", "", "", "", "", "yes"],
    ]),
}


@dataclass(frozen=True)
class RowIssue:
    row: int            # 1 = the first data row under the header
    message: str


@dataclass
class AccountChoice:
    key: str
    code_in: str
    name_in: str
    match: AccountMatch
    chosen: str | None
    problem: str        # "" | unmapped | not_in_chart | inactive | locked
    rows: int = 0


_PROBLEM_TEXT = {"unmapped": "isn't mapped to an account", "not_in_chart": "is mapped to an account not in the chart",
                 "inactive": "is mapped to an inactive account", "locked": "is mapped to a locked account"}


def problem_text(a: AccountChoice) -> str:
    shown = " ".join(p for p in (a.code_in, a.name_in) if p) or "(blank)"
    target = f" ({a.chosen})" if a.chosen and a.problem in ("inactive", "locked") else ""
    return f"Account '{shown}' {_PROBLEM_TEXT[a.problem]}{target}"


class _Accounts:
    """The file's distinct accounts, each matched once, with the person's overrides applied."""

    def __init__(self, chart: list[AccountRef], overrides: dict[str, str]):
        self.chart = {a.code: a for a in chart}
        self.refs = chart
        self.overrides = overrides
        self.by_key: OrderedDict[str, AccountChoice] = OrderedDict()

    def resolve(self, code: str, name: str) -> AccountChoice:
        key = source_key(code, name)
        found = self.by_key.get(key)
        if found is None:
            match = match_account(code, name, self.refs)
            chosen = (self.overrides.get(key) or "").strip() or match.code
            found = AccountChoice(key, code.strip(), name.strip(), match, chosen or None, self._problem(chosen))
            self.by_key[key] = found
        found.rows += 1
        return found

    def _problem(self, code: str | None) -> str:
        if not code:
            return "unmapped"
        account = self.chart.get(code)
        if account is None:
            return "not_in_chart"
        if not account.active:
            return "inactive"
        return "locked" if account.locked else ""

    def check(self, code: str) -> str:
        return self._problem(code)

    @property
    def choices(self) -> list[AccountChoice]:
        return list(self.by_key.values())


def _getter(headers: list[str], columns: dict[str, str]):
    index = {f: headers.index(h) for f, h in columns.items() if h and h in headers}

    def get(row: list[str], f: str) -> str:
        i = index.get(f)
        return str(row[i]).strip() if i is not None and i < len(row) and row[i] is not None else ""
    return get, index


def _dates(rows: list[list[str]], get, fields: tuple[str, ...], date_format: str | None) -> tuple[str | None, list[str]]:
    values = [get(r, f) for r in rows for f in fields]
    detected, candidates = detect_date_format(values)
    if date_format:
        return date_format, candidates
    return detected, candidates


def _money(text: str, label: str, row: int, errors: list[RowIssue]) -> Decimal:
    try:
        value = parse_amount(text)
    except ValueError as exc:
        errors.append(RowIssue(row, f"{label}: {exc}"))
        return ZERO
    return (value or ZERO).quantize(Decimal("0.01"))


def _is_total(code: str, name: str) -> bool:
    return not re.match(r"^\d", code) and bool(re.match(r"^\s*(grand )?totals?\b", (name or code).lower()))


def _date_error(fmt: str | None, candidates: list[str]) -> RowIssue | None:
    if fmt:
        return None
    if candidates:
        shown = " or ".join(DATE_LABELS.get(c, c) for c in candidates[:3])
        return RowIssue(0, f"The dates could be read as {shown}; choose the date format.")
    return None


# --- opening trial balance ----------------------------------------------------------------------------------------

@dataclass
class TbRow:
    row: int
    code_in: str
    name_in: str
    debit: Decimal
    credit: Decimal
    key: str


@dataclass
class TbResult:
    rows: list[TbRow] = field(default_factory=list)
    lines: list[tuple[str, Decimal, Decimal]] = field(default_factory=list)
    accounts: list[AccountChoice] = field(default_factory=list)
    debit: Decimal = ZERO
    credit: Decimal = ZERO
    difference: Decimal = ZERO          # debit − credit, after the difference line (0 when it balances)
    raw_difference: Decimal = ZERO      # before any difference line
    as_of: date | None = None
    date_format: str | None = None
    date_candidates: list[str] = field(default_factory=list)
    errors: list[RowIssue] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return (not self.errors and len(self.lines) >= 2 and self.difference == 0
                and all(not a.problem for a in self.accounts))


def build_tb(headers: list[str], rows: list[list[str]], columns: dict[str, str], chart: list[AccountRef],
             overrides: dict[str, str], *, date_format: str | None = None, books_start: date | None = None,
             difference_account: str | None = None) -> TbResult:
    get, index = _getter(headers, columns)
    out = TbResult()
    if not ({"account_code", "account_name"} & set(index)):
        out.errors.append(RowIssue(0, "Map the account code or account name column."))
    if not ({"debit", "credit", "balance"} & set(index)):
        out.errors.append(RowIssue(0, "Map the debit and credit columns (or one signed balance column)."))
    if out.errors:
        return out
    accounts = _Accounts(chart, overrides)
    net: dict[str, Decimal] = {}
    as_of: set[date] = set()
    fmt, out.date_candidates = _dates(rows, get, ("as_of",), date_format) if "as_of" in index else (None, [])
    out.date_format = fmt
    for n, row in enumerate(rows, start=1):
        code, name = get(row, "account_code"), get(row, "account_name")
        if not code and not name or _is_total(code, name):
            continue
        before = len(out.errors)
        amount = (_money(get(row, "debit"), "Debit", n, out.errors) - _money(get(row, "credit"), "Credit", n, out.errors)
                  + _money(get(row, "balance"), "Balance", n, out.errors))
        if fmt and get(row, "as_of"):
            try:
                as_of.add(parse_date(get(row, "as_of"), fmt))
            except ValueError as exc:
                out.warnings.append(f"Row {n}: {exc}")
        if len(out.errors) > before or amount == 0:
            continue
        choice = accounts.resolve(code, name)
        out.rows.append(TbRow(n, code, name, max(amount, ZERO), max(-amount, ZERO), choice.key))
        if choice.chosen:
            net[choice.chosen] = net.get(choice.chosen, ZERO) + amount
    err = _date_error(fmt, out.date_candidates) if "as_of" in index else None
    if err:
        out.warnings.append(err.message.replace("choose the date format", "choose the date format to check the as-of"))
    out.accounts = accounts.choices
    out.raw_difference = sum(net.values(), ZERO)
    if out.raw_difference and difference_account:
        problem = accounts.check(difference_account)
        if problem:
            out.errors.append(RowIssue(0, f"The difference can't go to {difference_account}: the account is "
                                          f"{'not in the chart' if problem == 'not_in_chart' else problem}."))
        else:
            net[difference_account] = net.get(difference_account, ZERO) - out.raw_difference
    out.lines = sorted(((c, max(v, ZERO), max(-v, ZERO)) for c, v in net.items() if v != 0), key=lambda x: x[0])
    out.debit = sum((d for _, d, _ in out.lines), ZERO)
    out.credit = sum((c for _, _, c in out.lines), ZERO)
    out.difference = out.debit - out.credit
    if len(as_of) > 1:
        out.warnings.append("The sheet has more than one as-of date: " + ", ".join(sorted(d.isoformat() for d in as_of)))
    out.as_of = min(as_of) if as_of else None
    if out.as_of and books_start and out.as_of not in (books_start, books_start - timedelta(days=1)):
        out.warnings.append(f"The trial balance is as of {out.as_of:%b %d, %Y}, but the books start on "
                            f"{books_start:%b %d, %Y}; the opening balances are posted on the books start.")
    for a in out.accounts:
        if a.problem:
            out.errors.append(RowIssue(0, problem_text(a)))
    return out


# --- opening open items -------------------------------------------------------------------------------------------

_AR_WORDS = ("ar", "a/r", "receivable", "receivables", "customer", "invoice", "sales", "sale", "r")
_AP_WORDS = ("ap", "a/p", "payable", "payables", "supplier", "vendor", "bill", "purchase", "p")


@dataclass(frozen=True)
class OpenItemDraft:
    row: int
    kind: str                   # ar | ap
    contact_name: str
    contact_tin: str
    doc_number: str
    doc_date: date
    due_date: date | None
    terms_days: int | None
    amount: Decimal


@dataclass
class OpenResult:
    items: list[OpenItemDraft] = field(default_factory=list)
    totals: dict[str, Decimal] = field(default_factory=dict)
    date_format: str | None = None
    date_candidates: list[str] = field(default_factory=list)
    skipped: int = 0            # already imported (same type, party and number)
    errors: list[RowIssue] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return not self.errors and bool(self.items)


def item_key(kind: str, name: str, doc_number: str) -> tuple[str, str, str]:
    return kind, norm_name(name), doc_number.strip().upper()


def _kind(text: str, default: str | None) -> str | None:
    t = text.strip().lower().replace(".", "")
    if not t:
        return default
    if t in _AR_WORDS or "receiv" in t or "customer" in t:
        return "ar"
    if t in _AP_WORDS or "payab" in t or "supplier" in t or "vendor" in t:
        return "ap"
    return None


def _terms(text: str) -> int | None:
    found = re.search(r"\d{1,3}", text or "")
    return int(found.group()) if found else None


def build_open_items(headers: list[str], rows: list[list[str]], columns: dict[str, str], books_start: date, *,
                     default_kind: str | None = None, date_format: str | None = None,
                     existing: set[tuple[str, str, str]] | frozenset = frozenset()) -> OpenResult:
    get, index = _getter(headers, columns)
    out = OpenResult()
    missing = [OPEN_FIELDS[f] for f in ("contact_name", "doc_date", "amount") if f not in index]
    if missing:
        out.errors.append(RowIssue(0, "Map the columns: " + ", ".join(missing) + "."))
        return out
    if "kind" not in index and default_kind not in ("ar", "ap"):
        out.errors.append(RowIssue(0, "Map the Type column or say whether the sheet is receivables or payables."))
        return out
    fmt, out.date_candidates = _dates(rows, get, ("doc_date", "due_date"), date_format)
    out.date_format = fmt
    err = _date_error(fmt, out.date_candidates)
    if err or not fmt:
        out.errors.append(err or RowIssue(0, "Couldn't read the dates in the date column."))
        return out
    seen: set[tuple[str, str, str]] = set()
    for n, row in enumerate(rows, start=1):
        name = get(row, "contact_name")
        if not name or _is_total("", name):
            continue
        kind = _kind(get(row, "kind"), default_kind)
        if kind is None:
            out.errors.append(RowIssue(n, f"Type '{get(row, 'kind')}' isn't AR or AP."))
            continue
        before = len(out.errors)
        amount = _money(get(row, "amount"), "Amount", n, out.errors)
        try:
            doc_date = parse_date(get(row, "doc_date"), fmt) if get(row, "doc_date") else None
            due = parse_date(get(row, "due_date"), fmt) if get(row, "due_date") else None
        except ValueError as exc:
            out.errors.append(RowIssue(n, str(exc)))
            continue
        if len(out.errors) > before:
            continue
        if doc_date is None:
            out.errors.append(RowIssue(n, "The invoice date is blank."))
            continue
        if doc_date >= books_start:
            out.errors.append(RowIssue(n, f"Dated {doc_date:%b %d, %Y}: opening items are invoices from before the "
                                          f"books start ({books_start:%b %d, %Y}); upload later ones as documents."))
            continue
        if amount == 0:
            out.errors.append(RowIssue(n, "The amount is zero."))
            continue
        doc_number = get(row, "doc_number")[:60]
        key = item_key(kind, name, doc_number)
        if key in existing:
            out.skipped += 1
            continue
        if key in seen:
            out.errors.append(RowIssue(n, f"{doc_number or 'This invoice'} for {name} is in the sheet twice."))
            continue
        seen.add(key)
        digits = re.sub(r"\D", "", get(row, "contact_tin"))
        if digits and len(digits) < 9:
            out.warnings.append(f"Row {n}: TIN '{get(row, 'contact_tin')}' has fewer than 9 digits; left blank.")
        if amount < 0:
            out.warnings.append(f"Row {n}: a negative amount is kept as a credit (credit memo / advance).")
        out.items.append(OpenItemDraft(n, kind, name[:255], digits[:9] if len(digits) >= 9 else "", doc_number,
                                       doc_date, due, _terms(get(row, "terms_days")), amount))
        out.totals[kind] = out.totals.get(kind, ZERO) + amount
    if len(out.items) > MAX_OPEN_ITEMS:
        out.errors.append(RowIssue(0, f"Import at most {MAX_OPEN_ITEMS} open items at a time."))
    if out.skipped:
        out.warnings.append(f"{out.skipped} item(s) were imported before (same type, party and number) and are skipped.")
    return out


def control_tie(items: dict[str, Decimal], control: dict[str, Decimal]) -> list[str]:
    """A warning per side whose open items don't add up to the opening balance of its control account."""
    out = []
    for kind, label in (("ar", "receivable"), ("ap", "payable")):
        have, want = items.get(kind, ZERO), control.get(kind, ZERO)
        if have != want:
            out.append(f"Open {label} items total ₱{have:,.2f} but the opening balances carry ₱{want:,.2f} of accounts "
                       f"{label} (difference ₱{abs(want - have):,.2f}). Aging and the books won't agree until they "
                       "match.")
    return out


# --- journal entries ----------------------------------------------------------------------------------------------

@dataclass
class JeDraft:
    key: str
    row: int
    entry_date: date | None
    reference: str = ""
    particulars: str = ""
    is_adjusting: bool = False
    lines: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    posts_on: date | None = None        # the day it lands (the first open day for a closed month)

    @property
    def debit(self) -> Decimal:
        return sum((l["debit"] for l in self.lines), ZERO)

    @property
    def credit(self) -> Decimal:
        return sum((l["credit"] for l in self.lines), ZERO)


@dataclass
class JeResult:
    entries: list[JeDraft] = field(default_factory=list)
    accounts: list[AccountChoice] = field(default_factory=list)
    date_format: str | None = None
    date_candidates: list[str] = field(default_factory=list)
    errors: list[RowIssue] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return (not self.errors and bool(self.entries) and all(not e.errors for e in self.entries)
                and all(not a.problem for a in self.accounts))


def _yes(text: str) -> bool:
    return text.strip().lower() in ("y", "yes", "1", "true", "x", "aje", "adj", "adjusting", "✓")


def build_journals(headers: list[str], rows: list[list[str]], columns: dict[str, str], chart: list[AccountRef],
                   overrides: dict[str, str], *, books_start: date, date_format: str | None = None,
                   last_closed: date | None = None) -> JeResult:
    get, index = _getter(headers, columns)
    out = JeResult()
    if "date" not in index:
        out.errors.append(RowIssue(0, "Map the date column."))
    if not ({"account_code", "account_name"} & set(index)):
        out.errors.append(RowIssue(0, "Map the account code or account name column."))
    if not ({"debit", "credit", "amount"} & set(index)):
        out.errors.append(RowIssue(0, "Map the debit and credit columns (or one signed amount column)."))
    if out.errors:
        return out
    fmt, out.date_candidates = _dates(rows, get, ("date",), date_format)
    out.date_format = fmt
    err = _date_error(fmt, out.date_candidates)
    if err or not fmt:
        out.errors.append(err or RowIssue(0, "Couldn't read the dates in the date column."))
        return out
    accounts = _Accounts(chart, overrides)
    drafts: OrderedDict[str, JeDraft] = OrderedDict()
    current: JeDraft | None = None
    keys: dict[str, list[str]] = {}
    for n, row in enumerate(rows, start=1):
        code, name = get(row, "account_code"), get(row, "account_name")
        if not code and not name or _is_total(code, name):
            continue
        raw_date = get(row, "date")
        try:
            on = parse_date(raw_date, fmt) if raw_date else None
        except ValueError as exc:
            out.errors.append(RowIssue(n, str(exc)))
            continue
        if "journal_no" in index:
            group = get(row, "journal_no")
            key = f"no:{group}" if group else (current.key if current else f"row:{n}")
        else:
            key = f"{on.isoformat()}|{get(row, 'reference')}" if on else (current.key if current else f"row:{n}")
        draft = drafts.get(key)
        if draft is None:
            draft = drafts[key] = JeDraft(key, n, on)
        current = draft
        if on and draft.entry_date is None:
            draft.entry_date = on
        elif on and on != draft.entry_date and f"Rows have different dates ({draft.entry_date}, {on})" not in \
                draft.errors:
            draft.errors.append(f"Rows have different dates ({draft.entry_date}, {on})")
        draft.reference = draft.reference or get(row, "reference")[:60]
        draft.particulars = draft.particulars or get(row, "description")[:255]
        draft.is_adjusting = draft.is_adjusting or _yes(get(row, "adjusting"))
        issues: list[RowIssue] = []
        amount = (_money(get(row, "debit"), "Debit", n, issues) - _money(get(row, "credit"), "Credit", n, issues)
                  + _money(get(row, "amount"), "Amount", n, issues))
        if issues:
            out.errors.extend(issues)
            continue
        if amount == 0:
            continue
        choice = accounts.resolve(code, name)
        keys.setdefault(key, []).append(choice.key)
        draft.lines.append({"account_code": choice.chosen or "", "debit": max(amount, ZERO),
                            "credit": max(-amount, ZERO), "party_name": get(row, "party_name")[:255],
                            "party_tin": re.sub(r"\D", "", get(row, "party_tin"))[:9]})
    out.accounts = accounts.choices
    by_key = {a.key: a for a in out.accounts}
    first_open = last_closed + timedelta(days=1) if last_closed else None
    for draft in drafts.values():
        if draft.entry_date is None:
            draft.errors.append("No date on the entry's rows")
        elif draft.entry_date < books_start:
            draft.errors.append(f"Dated {draft.entry_date:%b %d, %Y}, before the books start ({books_start:%b %d, %Y})")
        else:
            draft.posts_on = first_open if first_open and draft.entry_date <= last_closed else draft.entry_date
        if len(draft.lines) < 2:
            draft.errors.append("An entry needs at least two lines")
        if len(draft.lines) > MAX_LINES:
            draft.errors.append(f"An entry can have at most {MAX_LINES} lines")
        if draft.debit != draft.credit:
            draft.errors.append(f"Debits ({draft.debit:,.2f}) and credits ({draft.credit:,.2f}) don't balance")
        for k in dict.fromkeys(keys.get(draft.key, [])):
            a = by_key[k]
            if a.problem:
                draft.errors.append(problem_text(a))
        out.entries.append(draft)
    if len(out.entries) > MAX_ENTRIES:
        out.errors.append(RowIssue(0, f"Import at most {MAX_ENTRIES} journal entries at a time."))
    closed = sum(1 for d in out.entries if d.posts_on and d.entry_date and d.posts_on != d.entry_date)
    if closed:
        out.warnings.append(f"{closed} entr{'y is' if closed == 1 else 'ies are'} dated in a closed month and will "
                            f"post as correcting entries on {first_open:%b %d, %Y}; the closed pages stay as printed.")
    return out
