# AutoAccounting Books — Phase 1 (Ledger core) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every quarter's Generate also produces the client's books — Sales, Purchase, Cash Receipts, Cash Disbursements and General journals, General Ledger, AR/AP subsidiary ledgers and trial balance — from the sorted documents, payments, filed returns, the asset register and typed journal entries.

**Architecture:** A pure posting engine (`compute/books.py`) turns documents, payments, quarter tax forms, depreciation and manual entries into balanced journal entries; a pure ledger builder (`compute/book_ledgers.py`) turns entries into keyed workbook rows. A small async loader (`services/accounting/books/loader.py`) gathers the inputs and is called from the existing quarter Generate, so books land in the same versioned workbook with the same yellow change highlighting. New persistent state is only the chart of accounts, typed journal entries, payment fields on documents and receipt links.

**Tech Stack:** FastAPI + async SQLAlchemy + Pydantic v2 (backend), pytest (pure tests, run in the backend container), Next.js 15 + React 19 + Tailwind 4 (frontend).

**Spec:** `docs/superpowers/specs/2026-10-09-autoaccounting-books-design.md` (§1–4, §5.1, §6, §7). Phase 2 (closing months, loose-leaf PDFs, `aa_book_closes`) and phase 3 (year-end, FS) are **not** in this plan.

## Global Constraints

- New code lives under `backend/app/services/accounting/books/`, `backend/app/services/accounting/compute/books.py`, `compute/book_ledgers.py`, `backend/app/routers/accounting_books.py`, `backend/app/schemas/accounting_books.py`, `frontend/src/components/accounting/` — don't touch other modules (user rule: "dont touch other modules").
- New `aa_*` tables: created by `create_all`; columns for existing tables added in `services/accounting/schema.py::column_statements` (`ADD COLUMN IF NOT EXISTS`); FORCE RLS via `services/accounting/rls.py::_FIRM_TABLES`.
- Accrual basis, periodic inventory. Every entry balances; the engine raises `ValueError` on an unbalanced entry.
- Amounts reuse the returns engine: `split_vat_sales`, `cost_base`, `claims_input_vat`, `is_capital_goods`, `compute_ewt(...).by_line()`, `depreciation_between`.
- Money is `Decimal`, rounded with `compute.money.c2`.
- A company with `books_start` null gets no books at all (no tabs, no warnings, no staleness).
- Feature stays behind the existing `accounting` toggle (ships off).
- Run backend tests in the container: `docker compose exec -T backend python -m pytest -q <path>`. Frontend: `cd frontend && npm run lint && npm run build` on the host.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Deliberate simplifications vs the spec (phase 1): the Sales Journal uses one column set for VAT and non-VAT companies (VAT columns are zero for non-VAT); "deactivating an account with a balance is refused" is implemented as "refused while journal entries or documents use it"; the chart editor opens from the Books panel.
- Tailwind `dark:` doesn't follow the app theme here — use the theme CSS vars (`var(--bg-primary)` etc.) as the existing accounting components do.

## Review Focus

1. **Invoice + its official/collection receipt both uploaded** → the sale/expense is counted once on every return and posts once in the books, with the receipt as the collection/payment. (Task 4 test `test_linked_receipt_is_left_out_of_returns`, Task 3 matching tests, Task 6 payment test.)
2. **Credit memo (negative sale or purchase)** → posts a balanced reversing entry (Dr Sales returns / Cr AR), never raises. (Task 6 `test_credit_memo_posts_to_sales_returns`.)
3. **Payment dated before books start or after the quarter** → before start it only reduces the balance (opening TB already holds it); after the quarter it isn't posted yet. (Task 6 `test_payment_windows`.)
4. **A company seeded with an older chart missing a newer system account** → generation backfills the missing standard accounts instead of failing with `KeyError`. (Task 1 `test_missing_standard_accounts`.)
5. **Unbalanced or one-sided manual entry, or one dated before the books start** → rejected with 422/400 and a readable message; nothing saved. (Task 10 schema tests + router guard.)

---

### Task 1: Chart of accounts (pure)

**Files:**
- Create: `backend/app/services/accounting/books/__init__.py` (empty)
- Create: `backend/app/services/accounting/books/chart.py`
- Test: `backend/tests/test_aa_books_chart.py`

**Interfaces:**
- Produces: `ChartAccount(code, name, type, contra=False, system_key=None, parent_code=None, active=True)` with `.debit_normal`; `standard_chart(taxpayer_type: str) -> list[ChartAccount]`; `missing_standard(existing: list[ChartAccount], taxpayer_type: str) -> list[ChartAccount]`; `default_books(vat_registered: bool) -> list[str]`; `Chart(accounts)` with `.get(code) -> ChartAccount | None`, `.code(system_key) -> str` (raises `KeyError`), `.name(code) -> str`, `.doc_account(account: str, override: str = "") -> str`, `.accounts -> list[ChartAccount]` (sorted by code). Constants `ACCOUNT_TYPES`, `JOURNAL_BOOKS = ("SJ", "PJ", "CRJ", "CDJ", "GJ")`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_aa_books_chart.py
from app.services.accounting.books.chart import (
    Chart, ChartAccount, default_books, missing_standard, standard_chart,
)
from app.services.accounting.extraction import EXPENSE_ACCOUNTS


def test_codes_and_system_keys_are_unique():
    chart = standard_chart("corporation")
    codes = [a.code for a in chart]
    keys = [a.system_key for a in chart if a.system_key]
    assert len(codes) == len(set(codes)) and len(keys) == len(set(keys))


def test_every_document_account_maps_to_a_chart_account():
    chart = Chart(standard_chart("corporation"))
    for account in EXPENSE_ACCOUNTS:
        assert chart.get(chart.doc_account(account)) is not None, account
    assert chart.doc_account("capital_goods") == chart.code("ppe")
    assert chart.doc_account("no_such_account") == chart.code("doc:other")


def test_equity_account_name_follows_taxpayer_type():
    names = {t: Chart(standard_chart(t)).name(Chart(standard_chart(t)).code("capital"))
             for t in ("corporation", "individual", "partnership")}
    assert names == {"corporation": "Share capital", "individual": "Owner's capital",
                     "partnership": "Partners' capital"}


def test_normal_balances():
    chart = Chart(standard_chart("corporation"))
    assert chart.get(chart.code("cash")).debit_normal
    assert not chart.get(chart.code("accum_dep")).debit_normal      # contra asset
    assert not chart.get(chart.code("sales")).debit_normal
    assert chart.get(chart.code("sales_returns")).debit_normal      # contra income
    assert chart.get(chart.code("drawings")).debit_normal           # contra equity


def test_override_used_only_when_active():
    accounts = standard_chart("corporation") + [
        ChartAccount("6021", "Rent - warehouse", "expense", parent_code="6020"),
        ChartAccount("6022", "Rent - old", "expense", parent_code="6020", active=False),
    ]
    chart = Chart(accounts)
    assert chart.doc_account("rent", "6021") == "6021"
    assert chart.doc_account("rent", "6022") == chart.code("doc:rent")
    assert chart.doc_account("rent", "9999") == chart.code("doc:rent")


def test_missing_standard_accounts():
    full = standard_chart("corporation")
    older = [a for a in full if a.system_key != "input_vat_expense"]
    missing = missing_standard(older, "corporation")
    assert [a.system_key for a in missing] == ["input_vat_expense"]
    assert missing_standard(full, "corporation") == []


def test_unknown_system_key_raises():
    import pytest
    with pytest.raises(KeyError):
        Chart([]).code("cash")


def test_default_books():
    assert default_books(True) == ["SJ", "PJ", "CRJ", "CDJ", "GJ", "GL"]
    assert default_books(False) == ["CRJ", "CDJ", "GJ", "GL"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec -T backend python -m pytest -q tests/test_aa_books_chart.py`
Expected: FAIL — `ModuleNotFoundError: app.services.accounting.books`

- [ ] **Step 3: Write the implementation**

```python
# backend/app/services/accounting/books/chart.py
"""Chart of accounts: the standard PH SME chart and the lookups the posting engine uses (pure)."""

from collections.abc import Iterable
from dataclasses import dataclass

ACCOUNT_TYPES = ("asset", "liability", "equity", "income", "cost", "expense")
JOURNAL_BOOKS = ("SJ", "PJ", "CRJ", "CDJ", "GJ")
_DEBIT_TYPES = frozenset({"asset", "cost", "expense"})
_CAPITAL = {"corporation": "Share capital", "individual": "Owner's capital", "partnership": "Partners' capital"}


@dataclass(frozen=True)
class ChartAccount:
    code: str
    name: str
    type: str
    contra: bool = False
    system_key: str | None = None
    parent_code: str | None = None
    active: bool = True

    @property
    def debit_normal(self) -> bool:
        return (self.type in _DEBIT_TYPES) != self.contra


# (code, name, type, contra, system_key); "capital" is renamed per taxpayer type.
_STANDARD = (
    ("1010", "Cash on hand", "asset", False, "cash"),
    ("1020", "Cash in bank", "asset", False, "bank"),
    ("1030", "E-wallet", "asset", False, "ewallet"),
    ("1100", "Accounts receivable - trade", "asset", False, "ar"),
    ("1200", "Merchandise / materials inventory", "asset", False, "inventory"),
    ("1300", "Input VAT", "asset", False, "input_vat"),
    ("1320", "Creditable withholding tax", "asset", False, "cwt"),
    ("1500", "Property and equipment", "asset", False, "ppe"),
    ("1510", "Accumulated depreciation", "asset", True, "accum_dep"),
    ("2010", "Accounts payable - trade", "liability", False, "ap"),
    ("2100", "Output VAT", "liability", False, "output_vat"),
    ("2110", "VAT payable", "liability", False, "vat_payable"),
    ("2120", "Percentage tax payable", "liability", False, "pt_payable"),
    ("2130", "Expanded withholding tax payable", "liability", False, "ewt_payable"),
    ("2140", "Withholding tax on compensation payable", "liability", False, "wtc_payable"),
    ("2150", "Income tax payable", "liability", False, "it_payable"),
    ("2160", "Salaries payable", "liability", False, "salaries_payable"),
    ("2170", "SSS / PhilHealth / Pag-IBIG payable", "liability", False, None),
    ("2200", "Loans payable", "liability", False, None),
    ("3010", "Capital", "equity", False, "capital"),
    ("3020", "Retained earnings", "equity", False, "retained_earnings"),
    ("3030", "Drawings", "equity", True, "drawings"),
    ("3900", "Income summary", "equity", False, "income_summary"),
    ("4010", "Sales", "income", False, "sales"),
    ("4020", "Sales returns and discounts", "income", True, "sales_returns"),
    ("4100", "Other income", "income", False, "other_income"),
    ("5010", "Purchases", "cost", False, "doc:purchases"),
    ("5020", "Raw materials", "cost", False, "doc:raw_materials"),
    ("5030", "Importations", "cost", False, "doc:importation"),
    ("5090", "Cost of sales", "cost", False, "cogs"),
    ("6010", "Salaries and wages", "expense", False, "doc:salaries"),
    ("6020", "Rent", "expense", False, "doc:rent"),
    ("6030", "Utilities", "expense", False, "doc:utilities"),
    ("6040", "Professional fees", "expense", False, "doc:professional_fees"),
    ("6050", "Office supplies", "expense", False, "doc:office_supplies"),
    ("6060", "Representation", "expense", False, "doc:representation"),
    ("6070", "Transportation and travel", "expense", False, "doc:transportation"),
    ("6080", "Repairs and maintenance", "expense", False, "doc:repairs"),
    ("6090", "Taxes and licenses", "expense", False, "doc:taxes_licenses"),
    ("6100", "Depreciation", "expense", False, "depreciation"),
    ("6110", "Percentage tax", "expense", False, "pt_expense"),
    ("6120", "Non-creditable input VAT", "expense", False, "input_vat_expense"),
    ("6900", "Miscellaneous expenses", "expense", False, "doc:other"),
    ("7010", "Income tax expense", "expense", False, "income_tax"),
)


def standard_chart(taxpayer_type: str) -> list[ChartAccount]:
    capital = _CAPITAL.get(taxpayer_type, "Capital")
    return [ChartAccount(code, capital if key == "capital" else name, kind, contra, key)
            for code, name, kind, contra, key in _STANDARD]


def missing_standard(existing: list[ChartAccount], taxpayer_type: str) -> list[ChartAccount]:
    """Standard accounts whose system key and code are both absent (charts seeded before a key was added)."""
    keys = {a.system_key for a in existing if a.system_key}
    codes = {a.code for a in existing}
    return [a for a in standard_chart(taxpayer_type)
            if a.system_key and a.system_key not in keys and a.code not in codes]


def default_books(vat_registered: bool) -> list[str]:
    """Books registered by default: six for VAT taxpayers, four for non-VAT (RMO 29-2002 practice)."""
    return ["SJ", "PJ", "CRJ", "CDJ", "GJ", "GL"] if vat_registered else ["CRJ", "CDJ", "GJ", "GL"]


class Chart:
    def __init__(self, accounts: Iterable[ChartAccount]):
        self._by_code = {a.code: a for a in accounts}
        self._by_key = {a.system_key: a.code for a in self._by_code.values() if a.system_key}

    @property
    def accounts(self) -> list[ChartAccount]:
        return sorted(self._by_code.values(), key=lambda a: a.code)

    def get(self, code: str) -> ChartAccount | None:
        return self._by_code.get(code)

    def code(self, system_key: str) -> str:
        try:
            return self._by_key[system_key]
        except KeyError:
            raise KeyError(f"The chart of accounts has no account for {system_key!r}") from None

    def name(self, code: str) -> str:
        account = self._by_code.get(code)
        return account.name if account else code

    def doc_account(self, account: str, override: str = "") -> str:
        """The chart account a document account posts to; an active override (sub-account) wins."""
        chosen = self._by_code.get(override) if override else None
        if chosen is not None and chosen.active:
            return chosen.code
        if account == "capital_goods":
            return self.code("ppe")
        return self._by_key.get(f"doc:{account}") or self.code("doc:other")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose exec -T backend python -m pytest -q tests/test_aa_books_chart.py`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/accounting/books/__init__.py backend/app/services/accounting/books/chart.py backend/tests/test_aa_books_chart.py
git commit -m "feat(accounting): standard PH chart of accounts for the books

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Tables, columns and RLS

**Files:**
- Modify: `backend/app/models/accounting.py` (add `AAAccount`, `AAJournalEntry`; columns on `AACompany`, `AADocument`, `AASupplierRule`)
- Modify: `backend/app/services/accounting/schema.py`
- Modify: `backend/app/services/accounting/rls.py:16`
- Modify: `backend/tests/test_accounting_rls.py`
- Test: `backend/tests/test_aa_books_schema.py`

**Interfaces:**
- Produces: ORM `AAAccount` (`aa_accounts`: id, enterprise_id, company_id, code, name, type, contra, parent_code, system_key, active, created_at, updated_at; unique `uq_aa_account_code` on (company_id, code)); ORM `AAJournalEntry` (`aa_journal_entries`: id, enterprise_id, company_id, kind, book, entry_date, reference, particulars, lines JSONB, created_by, created_at, updated_at, deleted_at). New columns: `AACompany.books_kept` (JSONB list), `books_start` (Date|None), `books_signatory` (str), `books_signatory_title` (str), `books_updated_at` (datetime|None); `AADocument.paid_on` (Date|None), `paid_via` (str, "" | cash | bank | ewallet), `payment_ref` (str), `settles_document_id` (UUID|None, FK aa_documents SET NULL), `settles_source` (str, "" | auto | user), `gl_account_code` (str); `AASupplierRule.gl_account_code` (str).

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_aa_books_schema.py
from app.models.accounting import AAAccount, AACompany, AADocument, AAJournalEntry, AASupplierRule
from app.services.accounting.schema import column_statements


def test_new_columns_exist_on_models():
    assert {"books_kept", "books_start", "books_signatory", "books_signatory_title", "books_updated_at"} <= set(
        AACompany.__table__.columns.keys())
    assert {"paid_on", "paid_via", "payment_ref", "settles_document_id", "settles_source", "gl_account_code"} <= set(
        AADocument.__table__.columns.keys())
    assert "gl_account_code" in AASupplierRule.__table__.columns.keys()
    assert {"code", "name", "type", "contra", "parent_code", "system_key", "active"} <= set(
        AAAccount.__table__.columns.keys())
    assert {"kind", "book", "entry_date", "reference", "particulars", "lines", "deleted_at"} <= set(
        AAJournalEntry.__table__.columns.keys())


def test_existing_databases_get_every_new_column():
    sql = "\n".join(column_statements())
    for table, column in (
        ("aa_companies", "books_kept"), ("aa_companies", "books_start"), ("aa_companies", "books_signatory"),
        ("aa_companies", "books_signatory_title"), ("aa_companies", "books_updated_at"),
        ("aa_documents", "paid_on"), ("aa_documents", "paid_via"), ("aa_documents", "payment_ref"),
        ("aa_documents", "settles_document_id"), ("aa_documents", "settles_source"),
        ("aa_documents", "gl_account_code"), ("aa_supplier_rules", "gl_account_code"),
    ):
        assert f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} " in sql, (table, column)
    assert "CREATE INDEX IF NOT EXISTS ix_aa_documents_settles_document_id" in sql
```

Edit `backend/tests/test_accounting_rls.py` so the table list includes the new tables:

```python
from app.models.accounting import (
    AAAccount, AAAsset, AACompany, AADocument, AAFile, AAJournalEntry, AAOutput, AAPeriod, AASupplierRule, AAUpload,
)
from app.services.accounting.rls import rls_statements

TABLES = [m.__tablename__ for m in (AACompany, AAUpload, AAFile, AADocument, AASupplierRule, AAPeriod, AAOutput,
                                           AAAsset, AAAccount, AAJournalEntry)]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec -T backend python -m pytest -q tests/test_aa_books_schema.py tests/test_accounting_rls.py`
Expected: FAIL — `ImportError: cannot import name 'AAAccount'`

- [ ] **Step 3: Add the models and columns**

In `backend/app/models/accounting.py`, add to `AACompany` after `taxpayer_classification`:

```python
    # Books of accounts: null books_start = books off for this company.
    books_kept: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    books_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    books_signatory: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    books_signatory_title: Mapped[str] = mapped_column(String(60), nullable=False, default="", server_default="")
    # Set when the chart, journal entries or filed returns change: book tabs older than this are stale.
    books_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

Add to `AADocument` after `ewt_atc`:

```python
    paid_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    paid_via: Mapped[str] = mapped_column(String(10), nullable=False, default="", server_default="")
    payment_ref: Mapped[str] = mapped_column(String(60), nullable=False, default="", server_default="")
    # On a receipt: the invoice it pays (then it is payment evidence, not a sale or expense of its own).
    settles_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("aa_documents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    settles_source: Mapped[str] = mapped_column(String(5), nullable=False, default="", server_default="")
    gl_account_code: Mapped[str] = mapped_column(String(10), nullable=False, default="", server_default="")
```

Add to `AASupplierRule` after `ewt_atc`:

```python
    gl_account_code: Mapped[str] = mapped_column(String(10), nullable=False, default="", server_default="")
```

Append at the end of the file:

```python
class AAAccount(Base):
    """One account in a company's chart of accounts (seeded from the standard PH chart)."""

    __tablename__ = "aa_accounts"
    __table_args__ = (
        UniqueConstraint("company_id", "code", name="uq_aa_account_code"),
        Index("uq_aa_account_key", "company_id", "system_key", unique=True,
              postgresql_where=text("system_key IS NOT NULL")),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("aa_companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(10), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    type: Mapped[str] = mapped_column(String(12), nullable=False)
    contra: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    parent_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    system_key: Mapped[str | None] = mapped_column(String(40), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class AAJournalEntry(Base):
    """A journal entry typed by a person: the opening trial balance or a manual entry."""

    __tablename__ = "aa_journal_entries"
    __table_args__ = (Index("ix_aa_journal_entries_date", "company_id", "entry_date"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("aa_companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(10), nullable=False, default="manual")     # opening | manual
    book: Mapped[str] = mapped_column(String(5), nullable=False, default="GJ")          # GJ | CRJ | CDJ
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    reference: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    particulars: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # [{"account_code", "debit", "credit", "party_name", "party_tin"}], amounts as strings
    lines: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

Append to the list returned by `column_statements()` in `backend/app/services/accounting/schema.py`:

```python
        "ALTER TABLE aa_companies ADD COLUMN IF NOT EXISTS books_kept JSONB NOT NULL DEFAULT '[]'::jsonb",
        "ALTER TABLE aa_companies ADD COLUMN IF NOT EXISTS books_start DATE",
        "ALTER TABLE aa_companies ADD COLUMN IF NOT EXISTS books_signatory VARCHAR(120) NOT NULL DEFAULT ''",
        "ALTER TABLE aa_companies ADD COLUMN IF NOT EXISTS books_signatory_title VARCHAR(60) NOT NULL DEFAULT ''",
        "ALTER TABLE aa_companies ADD COLUMN IF NOT EXISTS books_updated_at TIMESTAMPTZ",
        "ALTER TABLE aa_documents ADD COLUMN IF NOT EXISTS paid_on DATE",
        "ALTER TABLE aa_documents ADD COLUMN IF NOT EXISTS paid_via VARCHAR(10) NOT NULL DEFAULT ''",
        "ALTER TABLE aa_documents ADD COLUMN IF NOT EXISTS payment_ref VARCHAR(60) NOT NULL DEFAULT ''",
        "ALTER TABLE aa_documents ADD COLUMN IF NOT EXISTS settles_document_id UUID "
        "REFERENCES aa_documents(id) ON DELETE SET NULL",
        "CREATE INDEX IF NOT EXISTS ix_aa_documents_settles_document_id ON aa_documents (settles_document_id)",
        "ALTER TABLE aa_documents ADD COLUMN IF NOT EXISTS settles_source VARCHAR(5) NOT NULL DEFAULT ''",
        "ALTER TABLE aa_documents ADD COLUMN IF NOT EXISTS gl_account_code VARCHAR(10) NOT NULL DEFAULT ''",
        "ALTER TABLE aa_supplier_rules ADD COLUMN IF NOT EXISTS gl_account_code VARCHAR(10) NOT NULL DEFAULT ''",
```

In `backend/app/services/accounting/rls.py`, extend `_FIRM_TABLES`:

```python
_FIRM_TABLES = ("aa_companies", "aa_uploads", "aa_files", "aa_documents", "aa_periods", "aa_outputs", "aa_assets",
                "aa_accounts", "aa_journal_entries")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec -T backend python -m pytest -q tests/test_aa_books_schema.py tests/test_accounting_rls.py tests/test_accounting_classify.py`
Expected: PASS

- [ ] **Step 5: Restart the backend and check the migration ran**

Run: `docker compose restart backend && sleep 8 && docker compose logs --tail=40 backend | grep -iE "error|traceback|startup" ; docker compose exec -T db psql -U postgres -d snagstock -c "\d aa_accounts" | head -20`
Expected: no traceback; `aa_accounts` table listed. (If the db service/user/database names differ, read them from `docker-compose.yml`.)

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/accounting.py backend/app/services/accounting/schema.py backend/app/services/accounting/rls.py backend/tests/test_aa_books_schema.py backend/tests/test_accounting_rls.py
git commit -m "feat(accounting): books tables, payment fields and receipt links

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Receipt matching (pure)

**Files:**
- Create: `backend/app/services/accounting/books/receipts.py`
- Modify: `backend/app/services/accounting/classify.py:12-16` (add `"possible_payment"` to `REVIEW_REASONS`)
- Test: `backend/tests/test_aa_books_receipts.py`

**Interfaces:**
- Produces: `is_payment_receipt(title: str, doc_type: str) -> bool`; `is_invoice(title: str, doc_type: str) -> bool`; `party_key(tin: str, name: str) -> str`; `DocRef(id: str, party: str, role: str, on: date | None, gross: Decimal, withholding: Decimal = 0)`; `Match(receipt_id: str, invoice_id: str | None, candidates: tuple[str, ...])`; `candidates_for(receipt: DocRef, invoices: list[DocRef], taken: set[str]) -> list[str]`; `match_receipts(receipts: list[DocRef], invoices: list[DocRef], taken: set[str] = frozenset()) -> list[Match]`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_aa_books_receipts.py
from datetime import date
from decimal import Decimal

from app.services.accounting.books.receipts import (
    DocRef, is_invoice, is_payment_receipt, match_receipts, party_key,
)

D = Decimal


def inv(id, gross, on=date(2026, 7, 1), party="111222333", role="seller", wt="0"):
    return DocRef(id, party, role, on, D(gross), D(wt))


def rcpt(id, gross, on=date(2026, 7, 20), party="111222333", role="seller"):
    return DocRef(id, party, role, on, D(gross))


def test_receipt_and_invoice_titles():
    assert is_payment_receipt("OFFICIAL RECEIPT", "receipt")
    assert is_payment_receipt("Collection Receipt", "other")
    assert is_payment_receipt("ACKNOWLEDGMENT RECEIPT", "invoice")
    assert not is_payment_receipt("SALES INVOICE", "invoice")
    assert not is_payment_receipt("SERVICE INVOICE / OFFICIAL RECEIPT", "receipt")  # a combined pre-EOPT form
    assert is_invoice("SALES INVOICE", "receipt") and is_invoice("", "invoice")


def test_party_key_prefers_tin():
    assert party_key("123456789", "Juan") == "123456789"
    assert party_key("", "Juan's  Store Inc.") == party_key("", "JUAN'S STORE INC")


def test_one_candidate_links():
    [m] = match_receipts([rcpt("r1", "1120")], [inv("i1", "1120"), inv("i2", "999")])
    assert (m.invoice_id, m.candidates) == ("i1", ())


def test_amount_net_of_withholding_matches():
    [m] = match_receipts([rcpt("r1", "1100")], [inv("i1", "1120", wt="20")])
    assert m.invoice_id == "i1"


def test_several_candidates_are_not_linked():
    [m] = match_receipts([rcpt("r1", "500")], [inv("i1", "500"), inv("i2", "500", on=date(2026, 7, 5))])
    assert m.invoice_id is None and set(m.candidates) == {"i1", "i2"}


def test_no_match_outside_window_party_role_or_amount():
    invoices = [inv("old", "500", on=date(2025, 12, 1)), inv("later", "500", on=date(2026, 8, 1)),
                inv("other", "500", party="999888777"), inv("buy", "500", role="buyer"), inv("amt", "502")]
    [m] = match_receipts([rcpt("r1", "500")], invoices)
    assert m.invoice_id is None and m.candidates == ()


def test_an_invoice_is_claimed_once_oldest_receipt_first():
    matches = match_receipts([rcpt("r2", "500", on=date(2026, 7, 25)), rcpt("r1", "500", on=date(2026, 7, 10))],
                             [inv("i1", "500")])
    assert {m.receipt_id: m.invoice_id for m in matches} == {"r1": "i1", "r2": None}


def test_taken_invoices_are_skipped():
    [m] = match_receipts([rcpt("r1", "500")], [inv("i1", "500")], taken={"i1"})
    assert m.invoice_id is None


def test_undated_receipt_never_matches():
    [m] = match_receipts([DocRef("r1", "111222333", "seller", None, D("500"))], [inv("i1", "500")])
    assert m.invoice_id is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec -T backend python -m pytest -q tests/test_aa_books_receipts.py`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
# backend/app/services/accounting/books/receipts.py
"""Match payment receipts (OR / collection / acknowledgement) to the invoice they pay (pure).

Since EOPT (RR 7-2024) the invoice is the primary evidence of a sale; a receipt only proves the
payment. A receipt linked to its invoice is left out of the returns and posts the cash movement.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from app.services.accounting.matching import normalize_name

WINDOW = timedelta(days=180)
TOLERANCE = Decimal("1.00")
_RECEIPT_WORDS = ("OFFICIAL RECEIPT", "COLLECTION RECEIPT", "ACKNOWLEDGEMENT RECEIPT", "ACKNOWLEDGMENT RECEIPT",
                  "PAYMENT RECEIPT", "PROVISIONAL RECEIPT")


def is_invoice(title: str, doc_type: str) -> bool:
    return doc_type == "invoice" or "INVOICE" in (title or "").upper()


def is_payment_receipt(title: str, doc_type: str) -> bool:
    upper = (title or "").upper()
    if "INVOICE" in upper:
        return False
    return doc_type == "receipt" or any(word in upper for word in _RECEIPT_WORDS)


def party_key(tin: str, name: str) -> str:
    return tin or f"NAME:{normalize_name(name or '')}"


@dataclass(frozen=True)
class DocRef:
    id: str
    party: str
    role: str                 # client_role: seller | buyer
    on: date | None
    gross: Decimal
    withholding: Decimal = Decimal("0")


@dataclass(frozen=True)
class Match:
    receipt_id: str
    invoice_id: str | None
    candidates: tuple[str, ...]


def _amount_fits(receipt: DocRef, invoice: DocRef) -> bool:
    return (abs(receipt.gross - invoice.gross) <= TOLERANCE
            or abs(receipt.gross - (invoice.gross - invoice.withholding)) <= TOLERANCE)


def candidates_for(receipt: DocRef, invoices: list[DocRef], taken: set[str]) -> list[str]:
    if receipt.on is None:
        return []
    return [i.id for i in invoices
            if i.id not in taken and i.party == receipt.party and i.role == receipt.role and i.on is not None
            and i.on <= receipt.on <= i.on + WINDOW and _amount_fits(receipt, i)]


def match_receipts(receipts: list[DocRef], invoices: list[DocRef], taken: set[str] = frozenset()) -> list[Match]:
    """Oldest receipt first; an automatically linked invoice can't be claimed by a later receipt."""
    claimed = set(taken)
    out: list[Match] = []
    for r in sorted(receipts, key=lambda r: (r.on or date.max, r.id)):
        found = candidates_for(r, invoices, claimed)
        if len(found) == 1:
            claimed.add(found[0])
            out.append(Match(r.id, found[0], ()))
        else:
            out.append(Match(r.id, None, tuple(found) if len(found) > 1 else ()))
    return out
```

In `backend/app/services/accounting/classify.py`, add `"possible_payment"` to the end of `REVIEW_REASONS`:

```python
REVIEW_REASONS = (
    "low_confidence", "missing_date", "missing_amount", "unsorted", "not_addressed_to_client",
    "seller_not_vat_registered", "not_an_invoice", "vat_math_mismatch", "possible_duplicate",
    "other_company_tin", "nothing_extracted", "possible_payment",
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose exec -T backend python -m pytest -q tests/test_aa_books_receipts.py tests/test_accounting_classify.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/accounting/books/receipts.py backend/app/services/accounting/classify.py backend/tests/test_aa_books_receipts.py
git commit -m "feat(accounting): match payment receipts to the invoices they pay

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Documents carry payment fields; linked receipts leave the returns

**Files:**
- Modify: `backend/app/services/accounting/compute/inputs.py` (`DocLine`: add `gl_account: str = ""`)
- Modify: `backend/app/routers/accounting_periods.py:64-91,124-128` (`doc_line`, `supplier_gl_rules`, `load_periods`)
- Modify: `backend/app/services/accounting/assets.py:16-19` (`is_asset_document`)
- Modify: `backend/app/schemas/accounting.py` (`DocumentOut`, `DocumentPatch`)
- Modify: `backend/app/routers/accounting.py:435-440,584-664` (`_PLAIN_FIELDS`, `_NULLABLE_FIELDS`, `_learn_supplier_rule`, `patch_document`)
- Test: `backend/tests/test_aa_books_documents.py`

**Interfaces:**
- Consumes: `AADocument` columns from Task 2.
- Produces: `DocLine.gl_account`; `doc_line(doc, atc_rules=None, gl_rules=None) -> DocLine`; `supplier_gl_rules(db, company_id) -> dict[str, str]`; `counts_on_returns(doc) -> bool` (in `accounting_periods`); `DocumentPatch` fields `paid_on`, `paid_via`, `payment_ref`, `gl_account_code`, `settles_document_id`; `DocumentOut` fields `paid_on`, `paid_via`, `payment_ref`, `settles_document_id`, `settles_source`, `gl_account_code`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_aa_books_documents.py
import uuid
from datetime import date
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.routers.accounting_periods import counts_on_returns, doc_line
from app.schemas.accounting import DocumentPatch
from app.services.accounting.assets import is_asset_document


def _doc(**kw):
    values = dict(
        id=uuid.uuid4(), category="purchases", account="capital_goods", doc_type="invoice", client_role="buyer",
        doc_date=date(2026, 7, 1), doc_number="1", seller_tin="111222333", seller_name="S", seller_address="",
        buyer_tin="", buyer_name="", buyer_address="", gross_amount=0, vatable_amount=0, vat_amount=0,
        exempt_amount=0, zero_rated_amount=0, withholding_amount=0, input_vat_valid=None, needs_review=False,
        reviewed=False, ewt_atc="", seller_vat_registered=None, gl_account_code="", settles_document_id=None,
        deleted_at=None, excluded=False,
    )
    values.update(kw)
    return SimpleNamespace(**values)


def test_linked_receipt_is_left_out_of_returns():
    assert counts_on_returns(_doc())
    assert not counts_on_returns(_doc(settles_document_id=uuid.uuid4()))


def test_linked_receipt_is_not_an_asset():
    assert is_asset_document(_doc())
    assert not is_asset_document(_doc(settles_document_id=uuid.uuid4()))


def test_doc_line_carries_gl_override_or_remembered_rule():
    assert doc_line(_doc(gl_account_code="6021")).gl_account == "6021"
    assert doc_line(_doc(), gl_rules={"111222333": "6022"}).gl_account == "6022"
    assert doc_line(_doc(gl_account_code="6021"), gl_rules={"111222333": "6022"}).gl_account == "6021"


def test_document_patch_payment_fields():
    p = DocumentPatch(paid_on=date(2026, 7, 9), paid_via="bank", payment_ref="CHK 001", gl_account_code="6021",
                      settles_document_id=uuid.uuid4())
    assert p.paid_via == "bank"
    assert DocumentPatch(paid_on=None).model_fields_set == {"paid_on"}
    with pytest.raises(ValidationError):
        DocumentPatch(paid_via="gcash")
    with pytest.raises(ValidationError):
        DocumentPatch(gl_account_code="12345678901")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec -T backend python -m pytest -q tests/test_aa_books_documents.py`
Expected: FAIL — `ImportError: cannot import name 'counts_on_returns'`

- [ ] **Step 3: Implement**

`backend/app/services/accounting/compute/inputs.py` — add the last field of `DocLine`:

```python
    counterparty_vat_registered: bool | None = None    # supplier printed a VAT REG TIN
    gl_account: str = ""                               # chart account override ("" = mapped from account)
```

`backend/app/routers/accounting_periods.py` — replace `doc_line` and add helpers right after it:

```python
def doc_line(doc: AADocument, atc_rules: dict[str, str] | None = None,
             gl_rules: dict[str, str] | None = None) -> DocLine:
    """A document as the engine sees it; a supplier's remembered ATC / GL account fills in when the document has none."""
    seller = doc.client_role == "seller"
    counterparty_tin = doc.buyer_tin if seller else doc.seller_tin
    remembered = "" if seller else (atc_rules or {}).get(counterparty_tin, "")
    gl = doc.gl_account_code or ("" if seller else (gl_rules or {}).get(counterparty_tin, ""))
    return DocLine(
        id=str(doc.id), category=doc.category, account=doc.account, doc_type=doc.doc_type,
        client_role=doc.client_role, doc_date=doc.doc_date, doc_number=doc.doc_number,
        counterparty_tin=counterparty_tin,
        counterparty_name=doc.buyer_name if seller else doc.seller_name,
        counterparty_address=doc.buyer_address if seller else doc.seller_address,
        gross=doc.gross_amount, vatable=doc.vatable_amount, vat=doc.vat_amount, exempt=doc.exempt_amount,
        zero_rated=doc.zero_rated_amount, withholding=doc.withholding_amount,
        input_vat_valid=doc.input_vat_valid, open_review=doc.needs_review and not doc.reviewed,
        ewt_atc=doc.ewt_atc or remembered,
        counterparty_vat_registered=None if seller else doc.seller_vat_registered,
        gl_account=gl,
    )


def counts_on_returns(doc: AADocument) -> bool:
    """A receipt linked to the invoice it pays is payment evidence, not a second sale or expense."""
    return doc.settles_document_id is None


async def supplier_gl_rules(db: AsyncSession, company_id: uuid.UUID) -> dict[str, str]:
    return dict((await db.execute(select(AASupplierRule.counterparty_tin, AASupplierRule.gl_account_code).where(
        AASupplierRule.company_id == company_id, AASupplierRule.gl_account_code != "",
    ))).all())
```

In `load_periods`, add the receipt filter to the query:

```python
    docs = (await db.execute(select(AADocument).where(
        AADocument.company_id == company.id, AADocument.deleted_at.is_(None), AADocument.excluded.is_(False),
        AADocument.period_year.is_not(None), AADocument.settles_document_id.is_(None), _docs_up_to(year, quarter),
    ))).scalars().all()
```

`backend/app/services/accounting/assets.py` — `is_asset_document`:

```python
def is_asset_document(doc: AADocument) -> bool:
    """A live capital-goods purchase: it depreciates; deleted, excluded, re-filed or receipt-linked documents drop out."""
    return (doc.deleted_at is None and not doc.excluded and doc.account == "capital_goods"
            and doc.category in ("purchases", "expenses") and doc.client_role == "buyer"
            and doc.settles_document_id is None)
```

`backend/app/schemas/accounting.py` — add to `DocumentOut` after `ewt_atc_effective`:

```python
    paid_on: date | None = None
    paid_via: str = ""
    payment_ref: str = ""
    settles_document_id: uuid.UUID | None = None
    settles_source: str = ""
    gl_account_code: str = ""
```

and to `DocumentPatch` after `excluded`:

```python
    paid_on: date | None = None
    paid_via: Literal["", "cash", "bank", "ewallet"] | None = None
    payment_ref: str | None = Field(default=None, max_length=60)
    gl_account_code: str | None = Field(default=None, max_length=10)
    settles_document_id: uuid.UUID | None = None
```

`backend/app/routers/accounting.py`:

```python
_PLAIN_FIELDS = (
    "category", "account", "doc_number", "doc_date", "seller_name", "seller_tin", "buyer_name",
    "buyer_tin", "gross_amount", "vatable_amount", "vat_amount", "exempt_amount",
    "zero_rated_amount", "withholding_amount", "vat_treatment", "reviewed", "excluded", "ewt_atc",
    "paid_on", "paid_via", "payment_ref",
)
_NULLABLE_FIELDS = {"doc_date", "paid_on"}
```

Replace `_learn_supplier_rule` so it can also learn the GL account:

```python
async def _learn_supplier_rule(db: AsyncSession, doc: AADocument, learn_atc: bool = False,
                               learn_gl: bool = False) -> None:
    tin = doc.buyer_tin if doc.client_role == "seller" else doc.seller_tin
    if not tin or doc.category not in ("purchases", "expenses"):
        return
    # Atomic upsert: two people correcting the same supplier at once must not 500.
    stmt = pg_insert(AASupplierRule).values(
        id=uuid.uuid4(), company_id=doc.company_id, counterparty_tin=tin, category=doc.category,
        account=doc.account, ewt_atc=doc.ewt_atc if learn_atc else "",
        gl_account_code=doc.gl_account_code if learn_gl else "", updated_at=datetime.now(timezone.utc),
    )
    learned = {"category": stmt.excluded.category, "account": stmt.excluded.account,
               "updated_at": stmt.excluded.updated_at}
    if learn_atc:
        learned["ewt_atc"] = stmt.excluded.ewt_atc
    if learn_gl:
        learned["gl_account_code"] = stmt.excluded.gl_account_code
    await db.execute(stmt.on_conflict_do_update(constraint="uq_aa_supplier_rule", set_=learned))
```

In `patch_document`, after the `_PLAIN_FIELDS` loop and before the `period_year` block, add GL and link handling (imports: `AAAccount` from `app.models.accounting`):

```python
    if "gl_account_code" in sent:
        code = (body.gl_account_code or "").strip()
        if code:
            account = (await db.execute(select(AAAccount).where(
                AAAccount.company_id == company.id, AAAccount.code == code, AAAccount.active.is_(True),
            ))).scalar_one_or_none()
            if account is None:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Account {code} isn't an active account in the chart")
        doc.gl_account_code = code

    if "settles_document_id" in sent:
        target_id = body.settles_document_id
        if target_id is not None:
            target = await _document_or_404(db, ent, target_id)
            if (target.id == doc.id or target.company_id != doc.company_id
                    or target.category not in ("sales", "purchases", "expenses", "payroll")
                    or target.client_role != doc.client_role or target.settles_document_id is not None):
                raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                    "A receipt can only pay a sale, purchase, expense or payroll document of the "
                                    "same company and side")
        doc.settles_document_id = target_id
        doc.settles_source = "user"   # never re-linked automatically after a person decides
        if "possible_payment" in (doc.review_reasons or []):
            doc.review_reasons = [r for r in doc.review_reasons if r != "possible_payment"]
            doc.needs_review = bool(doc.review_reasons)
```

and replace the supplier-rule line:

```python
    if sent & {"category", "account", "ewt_atc", "gl_account_code"}:
        await _learn_supplier_rule(db, doc, learn_atc="ewt_atc" in sent, learn_gl="gl_account_code" in sent)
```

- [ ] **Step 4: Run tests**

Run: `docker compose exec -T backend python -m pytest -q tests/test_aa_books_documents.py tests/test_aa_engine.py tests/test_accounting_schemas.py tests/test_aa_wiring.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/accounting/compute/inputs.py backend/app/routers/accounting_periods.py backend/app/services/accounting/assets.py backend/app/schemas/accounting.py backend/app/routers/accounting.py backend/tests/test_aa_books_documents.py
git commit -m "feat(accounting): payment fields and GL override on documents; linked receipts leave the returns

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Link receipts after uploads and edits; payments endpoint

**Files:**
- Create: `backend/app/services/accounting/books/links.py`
- Modify: `backend/app/services/accounting/pipeline.py` (end of the extraction job, before `upload.status = "done"`)
- Modify: `backend/app/routers/accounting.py` (`patch_document`, `delete_document`)
- Test: `backend/tests/test_aa_books_links.py`

**Interfaces:**
- Consumes: `receipts.py` (Task 3), document columns (Task 2).
- Produces: pure `plan_links(docs: list, ) -> dict[str, LinkChange]` where `LinkChange(settles: str | None, source: str, possible: bool)`; async `relink_receipts(db, company_id: uuid.UUID) -> None` (flushes, caller commits); `doc_ref(doc) -> DocRef`; `invoice_docs(docs) -> list`; `receipt_docs(docs) -> list`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_aa_books_links.py
import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.services.accounting.books.links import plan_links


def _d(title, doc_type, gross, on, **kw):
    values = dict(id=uuid.uuid4(), document_title=title, doc_type=doc_type, category="sales", client_role="seller",
                  doc_date=on, gross_amount=Decimal(gross), withholding_amount=Decimal("0"), buyer_tin="555666777",
                  buyer_name="Customer", seller_tin="123456789", seller_name="Client", settles_document_id=None,
                  settles_source="", deleted_at=None, excluded=False)
    values.update(kw)
    return SimpleNamespace(**values)


def test_auto_link_and_clear_when_no_longer_matching():
    invoice = _d("SALES INVOICE", "invoice", "1120", date(2026, 7, 1))
    receipt = _d("COLLECTION RECEIPT", "receipt", "1120", date(2026, 7, 9))
    plan = plan_links([invoice, receipt])
    assert plan[str(receipt.id)].settles == str(invoice.id) and plan[str(receipt.id)].source == "auto"

    receipt.settles_document_id, receipt.settles_source = invoice.id, "auto"
    receipt.gross_amount = Decimal("999")
    plan = plan_links([invoice, receipt])
    assert plan[str(receipt.id)].settles is None and plan[str(receipt.id)].source == ""


def test_user_decisions_are_kept_and_their_invoice_is_taken():
    invoice = _d("SALES INVOICE", "invoice", "500", date(2026, 7, 1))
    mine = _d("OFFICIAL RECEIPT", "receipt", "500", date(2026, 7, 2), settles_document_id=None, settles_source="user")
    other = _d("OFFICIAL RECEIPT", "receipt", "500", date(2026, 7, 3))
    plan = plan_links([invoice, mine, other])
    assert str(mine.id) not in plan                       # a person decided: left alone
    assert plan[str(other.id)].settles == str(invoice.id)

    mine.settles_document_id = invoice.id
    plan = plan_links([invoice, mine, other])
    assert plan[str(other.id)].settles is None            # the invoice is already paid by a user link


def test_several_candidates_flag_possible_payment():
    a = _d("SALES INVOICE", "invoice", "500", date(2026, 7, 1))
    b = _d("SALES INVOICE", "invoice", "500", date(2026, 7, 2))
    r = _d("OFFICIAL RECEIPT", "receipt", "500", date(2026, 7, 9))
    change = plan_links([a, b, r])[str(r.id)]
    assert change.settles is None and change.possible


def test_deleted_and_excluded_documents_are_ignored():
    invoice = _d("SALES INVOICE", "invoice", "500", date(2026, 7, 1), excluded=True)
    r = _d("OFFICIAL RECEIPT", "receipt", "500", date(2026, 7, 9))
    assert plan_links([invoice, r])[str(r.id)].settles is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec -T backend python -m pytest -q tests/test_aa_books_links.py`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# backend/app/services/accounting/books/links.py
"""Keep receipt → invoice links up to date for a company (pure planning + one async apply)."""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.accounting import AADocument
from app.services.accounting.books.receipts import DocRef, is_invoice, is_payment_receipt, match_receipts, party_key

_PAYABLE = ("sales", "purchases", "expenses", "payroll")


@dataclass(frozen=True)
class LinkChange:
    settles: str | None
    source: str        # "auto" when linked automatically, "" otherwise
    possible: bool     # several invoices fit: a person must choose


def doc_ref(doc) -> DocRef:
    seller = doc.client_role == "seller"
    return DocRef(str(doc.id), party_key(doc.buyer_tin if seller else doc.seller_tin,
                                         doc.buyer_name if seller else doc.seller_name),
                  doc.client_role, doc.doc_date, doc.gross_amount, doc.withholding_amount)


def _live(doc) -> bool:
    return doc.deleted_at is None and not doc.excluded


def receipt_docs(docs) -> list:
    return [d for d in docs if _live(d) and is_payment_receipt(d.document_title, d.doc_type)]


def invoice_docs(docs) -> list:
    return [d for d in docs if _live(d) and d.settles_document_id is None and d.category in _PAYABLE
            and is_invoice(d.document_title, d.doc_type)]


def plan_links(docs) -> dict[str, LinkChange]:
    """The link every automatically managed receipt should have. Receipts a person decided are left out."""
    receipts = receipt_docs(docs)
    auto = [r for r in receipts if r.settles_source != "user"]
    taken = {str(r.settles_document_id) for r in receipts
             if r.settles_source == "user" and r.settles_document_id is not None}
    matches = match_receipts([doc_ref(r) for r in auto], [doc_ref(i) for i in invoice_docs(docs)], taken)
    return {m.receipt_id: LinkChange(m.invoice_id, "auto" if m.invoice_id else "", bool(m.candidates))
            for m in matches}


async def relink_receipts(db: AsyncSession, company_id: uuid.UUID) -> None:
    """Apply plan_links to the company's documents (flushes; the caller commits)."""
    docs = (await db.execute(select(AADocument).where(
        AADocument.company_id == company_id, AADocument.deleted_at.is_(None),
    ))).scalars().all()
    by_id = {str(d.id): d for d in docs}
    for receipt_id, change in plan_links(docs).items():
        doc = by_id[receipt_id]
        target = uuid.UUID(change.settles) if change.settles else None
        if doc.settles_document_id != target or doc.settles_source != change.source:
            doc.settles_document_id, doc.settles_source = target, change.source
        reasons = [r for r in (doc.review_reasons or []) if r != "possible_payment"]
        if change.possible:
            reasons.append("possible_payment")
        if reasons != list(doc.review_reasons or []):
            doc.review_reasons = reasons
            doc.needs_review = bool(reasons)
    await db.flush()
```

In `backend/app/services/accounting/pipeline.py`, import `from app.services.accounting.books.links import relink_receipts` and, just before the final `upload = await db.get(AAUpload, upload_id)` / `upload.status = "done"`, add:

```python
        for company_id in company_ids:
            try:
                await relink_receipts(db, company_id)
                await db.commit()
            except Exception:  # linking is a convenience; never fail the upload over it
                logger.exception("accounting_relink_failed company_id=%s", company_id)
                await db.rollback()
```

In `backend/app/routers/accounting.py` (import `relink_receipts`), in `patch_document` before `await db.commit()`:

```python
    if sent & {"doc_date", "gross_amount", "withholding_amount", "seller_tin", "buyer_tin", "seller_name",
               "buyer_name", "category", "excluded", "settles_document_id"}:
        await db.flush()
        await relink_receipts(db, doc.company_id)
```

and in `delete_document` before `await db.commit()`:

```python
    await db.flush()
    await relink_receipts(db, doc.company_id)
```

- [ ] **Step 4: Run tests**

Run: `docker compose exec -T backend python -m pytest -q tests/test_aa_books_links.py tests/test_accounting_jobs.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/accounting/books/links.py backend/app/services/accounting/pipeline.py backend/app/routers/accounting.py backend/tests/test_aa_books_links.py
git commit -m "feat(accounting): link receipts to invoices after uploads and edits

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Posting engine — documents and payments (pure)

**Files:**
- Create: `backend/app/services/accounting/compute/books.py`
- Test: `backend/tests/test_aa_books_posting.py`

**Interfaces:**
- Consumes: `Chart` (Task 1), `DocLine.gl_account` (Task 4).
- Produces (used by Tasks 7–9):
  - `Line(account: str, debit: Decimal = ZERO, credit: Decimal = ZERO, party_name: str = "", party_tin: str = "")`
  - `Entry(id, date, book, reference, party_name, party_tin, particulars, source, lines: tuple[Line, ...], meta: tuple[tuple[str, Decimal], ...] = ())` with `.debits()`, `.credits()`, `.get(key) -> Decimal`
  - `Payment(id, settles, on: date, amount: Decimal | None, via: str, ref: str)`
  - `ManualEntry(id, kind, book, on: date, reference, particulars, lines: tuple[Line, ...])`
  - `QuarterTaxes(year, quarter, end: date, forms: dict)`; `FiledPayment(form, year, quarter, on: date, amount: Decimal)`
  - `BooksInput(company, chart, books_kept: frozenset[str], start: date, through: date, lines=(), ewt: dict[str, Decimal] = {}, payments=(), manual=(), quarters=(), filed=(), assets=())`
  - `make_entry(id, on, book, reference, party, particulars, source, *lines, meta=()) -> Entry | None` (None when every line is zero; raises `ValueError` when unbalanced)
  - `document_entries(line: DocLine, inp: BooksInput) -> list[Entry]`; `amount_due(line, inp) -> Decimal`; `payment_entries(inp, warnings: list[str]) -> list[Entry]`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_aa_books_posting.py
from datetime import date
from decimal import Decimal

import pytest

from app.services.accounting.books.chart import Chart, ChartAccount, default_books, standard_chart
from app.services.accounting.compute.books import (
    BooksInput, Line, Payment, document_entries, make_entry, payment_entries,
)
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
    return {(l.account, "Dr" if l.debit else "Cr"): l.debit or l.credit for l in entry.lines}


def test_unbalanced_entry_raises_and_empty_entry_is_none():
    with pytest.raises(ValueError):
        make_entry("x", date(2026, 1, 1), "GJ", "", ("", ""), "", "manual", Line("1010", debit=D("1")))
    assert make_entry("x", date(2026, 1, 1), "GJ", "", ("", ""), "", "manual", None) is None


def test_vat_sale_goes_to_the_sales_journal():
    [e] = document_entries(sale(gross="11200", vatable="10000", vat="1200", doc_number="SI-1"), books())
    assert e.book == "SJ" and e.reference == "SI-1"
    assert amounts(e) == {(C("ar"), "Dr"): D("11200.00"), (C("sales"), "Cr"): D("10000.00"),
                          (C("output_vat"), "Cr"): D("1200.00")}
    assert e.get("vatable") == D("10000")


def test_sale_goes_to_general_journal_when_no_sales_journal_is_kept():
    [e] = document_entries(sale(gross="500"), books(books_kept=frozenset(default_books(False))))
    assert e.book == "GJ"


def test_credit_memo_posts_to_sales_returns():
    [e] = document_entries(sale(gross="-1120", vatable="-1000", vat="-120"), books())
    assert amounts(e) == {(C("sales_returns"), "Dr"): D("1000.00"), (C("output_vat"), "Dr"): D("120.00"),
                          (C("ar"), "Cr"): D("1120.00")}


def test_purchase_with_input_vat_and_ewt():
    l = expense(account="rent", gross="11200", vat="1200", input_vat_valid=True)
    [e] = document_entries(l, books(ewt={l.id: D("500")}))
    assert e.book == "PJ"
    assert amounts(e) == {(C("doc:rent"), "Dr"): D("10000.00"), (C("input_vat"), "Dr"): D("1200.00"),
                          (C("ewt_payable"), "Cr"): D("500.00"), (C("ap"), "Cr"): D("10700.00")}


def test_unclaimed_input_vat_stays_in_the_cost_and_gl_override_wins():
    chart = Chart(standard_chart("corporation") + [ChartAccount("6051", "Supplies - store", "expense",
                                                                parent_code="6050")])
    l = expense(gross="1120", vat="120", input_vat_valid=False, gl_account="6051")
    [e] = document_entries(l, books(chart=chart))
    assert amounts(e) == {("6051", "Dr"): D("1120.00"), (C("ap"), "Cr"): D("1120.00")}


def test_capital_goods_post_to_property_and_equipment():
    l = purchase(account="capital_goods", gross="56000", vat="6000", input_vat_valid=True)
    [e] = document_entries(l, books())
    assert amounts(e)[(C("ppe"), "Dr")] == D("50000.00")


def test_payroll_and_received_2307():
    [p] = document_entries(line(category="payroll", account="salaries", gross="50000", withholding="2000"), books())
    assert amounts(p) == {(C("doc:salaries"), "Dr"): D("50000.00"), (C("wtc_payable"), "Cr"): D("2000.00"),
                          (C("salaries_payable"), "Cr"): D("48000.00")}
    [w] = document_entries(line(category="2307", account="2307_received", client_role="seller", gross="10000",
                                withholding="200"), books())
    assert amounts(w) == {(C("cwt"), "Dr"): D("200.00"), (C("ar"), "Cr"): D("200.00")}


def test_documents_that_never_post():
    for l in (line(category="2307", account="2307_issued", withholding="100"),
              line(category="support"), line(category="unsorted")):
        assert document_entries(l, books()) == []


def test_collection_with_paid_on_leaves_withholding_in_receivables():
    s = sale(gross="11200", vatable="10000", vat="1200", withholding="200", doc_number="SI-9")
    warnings: list[str] = []
    [e] = payment_entries(books(lines=(s,), payments=(Payment("p1", s.id, date(2026, 8, 3), None, "bank", ""),)),
                          warnings)
    assert e.book == "CRJ" and e.date == date(2026, 8, 3) and e.reference == "SI-9"
    assert amounts(e) == {(C("bank"), "Dr"): D("11000.00"), (C("ar"), "Cr"): D("11000.00")}
    assert warnings == []


def test_partial_receipts_and_overpayment_warning():
    b = purchase(gross="1000")
    pays = (Payment("r1", b.id, date(2026, 8, 1), D("400"), "cash", "OR-1"),
            Payment("r2", b.id, date(2026, 8, 5), D("700"), "cash", "OR-2"))
    warnings: list[str] = []
    out = payment_entries(books(lines=(b,), payments=pays), warnings)
    assert [e.book for e in out] == ["CDJ", "CDJ"]
    assert [amounts(e)[(C("ap"), "Dr")] for e in out] == [D("400.00"), D("700.00")]
    assert any("more than the balance" in w for w in warnings)


def test_payment_windows():
    b = purchase(gross="1000", doc_date=date(2025, 12, 1))
    pays = (Payment("early", b.id, date(2025, 12, 20), D("300"), "cash", ""),       # before books start
            Payment("now", b.id, date(2026, 2, 1), None, "cash", ""),              # the rest
            Payment("late", b.id, date(2026, 10, 2), D("50"), "cash", ""))         # after the quarter
    out = payment_entries(books(lines=(b,), payments=pays), [])
    assert [(e.id, amounts(e)[(C("ap"), "Dr")]) for e in out] == [("pay:now", D("700.00"))]


def test_payment_for_an_unknown_document_warns():
    warnings: list[str] = []
    assert payment_entries(books(payments=(Payment("p", "gone", date(2026, 2, 1), None, "cash", ""),)),
                           warnings) == []
    assert any("isn't in the books" in w for w in warnings)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec -T backend python -m pytest -q tests/test_aa_books_posting.py`
Expected: FAIL — `ModuleNotFoundError: app.services.accounting.compute.books`

- [ ] **Step 3: Implement**

```python
# backend/app/services/accounting/compute/books.py
"""Books of accounts: post documents, payments, taxes, depreciation and typed entries (pure).

Accrual basis, periodic inventory. Amounts come from the returns engine (cost_base, claims_input_vat,
computed EWT, depreciation_between) so the books and the returns agree.
"""

import calendar
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.services.accounting.books.chart import JOURNAL_BOOKS, Chart
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


def amount_due(l: DocLine, inp: BooksInput) -> Decimal:
    """What the counterparty pays / is paid in cash: net of tax withheld."""
    if l.category == "sales":
        return c2(l.gross - l.withholding)
    if l.category in ("purchases", "expenses"):
        return c2(l.gross - inp.ewt.get(l.id, ZERO))
    if l.category == "payroll":
        return c2(l.gross - l.withholding)
    return ZERO


def payment_entries(inp: BooksInput, warnings: list[str]) -> list[Entry]:
    chart = inp.chart
    by_id = {l.id: l for l in inp.lines}
    remaining: dict[str, Decimal] = {}
    out: list[Entry] = []
    unknown = over = 0
    for p in sorted(inp.payments, key=lambda p: (p.on, p.id)):
        l = by_id.get(p.settles)
        if l is None or amount_due(l, inp) == 0:
            unknown += 1
            continue
        if p.on > inp.through:
            continue
        left = remaining.setdefault(l.id, amount_due(l, inp))
        amount = c2(p.amount) if p.amount is not None else left
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
    if over:
        warnings.append(f"{over} payment(s) are more than the balance left on their document; the excess stays in "
                        "receivables / payables as an advance.")
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose exec -T backend python -m pytest -q tests/test_aa_books_posting.py`
Expected: PASS (15 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/accounting/compute/books.py backend/tests/test_aa_books_posting.py
git commit -m "feat(accounting): post documents and payments to the books

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Posting engine — taxes, depreciation, typed entries, `post_all` (pure)

**Files:**
- Modify: `backend/app/services/accounting/compute/books.py` (append)
- Test: `backend/tests/test_aa_books_taxes.py`

**Interfaces:**
- Consumes: Task 6 types; `PAYABLE_ITEM` from `compute/specs.py` (used by the loader, not here).
- Produces: `tax_entries(inp) -> list[Entry]`; `depreciation_entries(inp) -> list[Entry]`; `manual_entries(inp) -> list[Entry]`; `post_all(inp) -> tuple[list[Entry], list[str]]` (entries sorted by `(date, JOURNAL_BOOKS.index(book), id)`).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_aa_books_taxes.py
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


def test_vat_closing_with_excess_input_and_noncreditable_and_withheld():
    q = QuarterTaxes(2026, 3, date(2026, 9, 30), {"2550Q": {"37B": "1000.00", "60B": "1500.00", "61B": "-500.00",
                                                           "57B": "50.00", "16": "30.00"}})
    [e] = tax_entries(books(quarters=(q,)))
    assert amounts(e) == {(C("output_vat"), "Dr"): D("1000.00"), (C("input_vat"), "Cr"): D("1050.00"),
                          (C("input_vat_expense"), "Dr"): D("50.00"), (C("vat_payable"), "Dr"): D("30.00"),
                          (C("ar"), "Cr"): D("30.00")}


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


def test_post_all_orders_and_includes_typed_entries_in_window():
    opening = ManualEntry("o", "opening", "GJ", date(2026, 1, 1), "OB", "Opening balances",
                          (Line(C("cash"), debit=D("5000")), Line(C("capital"), credit=D("5000"))))
    later = ManualEntry("m", "manual", "GJ", date(2026, 12, 1), "", "", opening.lines)
    s = sale(gross="1120", vatable="1000", vat="120", doc_date=date(2026, 2, 1))
    entries, warnings = post_all(books(lines=(s,), manual=(opening, later)))
    assert [e.id for e in entries] == ["je:o", f"doc:{s.id}:sale"]
    assert entries[0].source == "opening" and warnings == []


def test_random_documents_always_give_a_balanced_ledger():
    rng = random.Random(7)
    lines, pays = [], []
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
    ewt = {l.id: D("10") for l in lines if l.category in ("purchases", "expenses")}
    entries, _ = post_all(books(lines=tuple(lines), payments=tuple(pays), ewt=ewt))
    assert sum((e.debits() for e in entries), D("0")) == sum((e.credits() for e in entries), D("0"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec -T backend python -m pytest -q tests/test_aa_books_taxes.py`
Expected: FAIL — `ImportError: cannot import name 'tax_entries'`

- [ ] **Step 3: Implement — append to `compute/books.py`**

```python
_PAID_ACCOUNT = (("2550Q", "vat_payable"), ("2551Q", "pt_payable"), ("0619E", "ewt_payable"),
                 ("1601EQ", "ewt_payable"), ("1601C", "wtc_payable"), ("1701Q", "it_payable"),
                 ("1702Q", "it_payable"))
_NO_PARTY = ("", "")


def _num(forms: dict, form: str, item: str) -> Decimal:
    value = forms.get(form, {}).get(item)
    return c2(value) if value not in (None, "") else ZERO


def _income_tax(forms: dict) -> tuple[Decimal, Decimal, Decimal] | None:
    """(tax due year to date, CWT credited this quarter, tax paid on earlier quarters) from a quarterly ITR."""
    if "1702Q" in forms:
        return _num(forms, "1702Q", "14"), _num(forms, "1702Q", "S4_5"), _num(forms, "1702Q", "S4_2")
    if "1701Q" in forms:
        due = "54" if "54" in forms["1701Q"] else "46"
        return _num(forms, "1701Q", due), _num(forms, "1701Q", "58"), _num(forms, "1701Q", "56")
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
        if "2550Q" in f:
            output = _num(f, "2550Q", "37B")
            applied = min(max(_num(f, "2550Q", "60B"), ZERO), max(output, ZERO))
            payable = max(_num(f, "2550Q", "61B"), ZERO) if output > 0 else ZERO
            noncreditable, withheld = _num(f, "2550Q", "57B"), _num(f, "2550Q", "16")
            out += _kept(make_entry(
                f"tax:2550Q:{tag}:close", q.end, "GJ", f"2550-Q {tag}", _NO_PARTY, "VAT for the quarter", "tax",
                _dr(code("output_vat"), max(output, ZERO)), _cr(code("input_vat"), applied),
                _cr(code("vat_payable"), payable),
                _dr(code("input_vat_expense"), noncreditable), _cr(code("input_vat"), noncreditable),
                _dr(code("vat_payable"), withheld), _cr(code("ar"), withheld),
            ))
        if "2551Q" in f:
            due, withheld = _num(f, "2551Q", "14"), _num(f, "2551Q", "15")
            out += _kept(make_entry(
                f"tax:2551Q:{tag}:accrue", q.end, "GJ", f"2551-Q {tag}", _NO_PARTY, "Percentage tax for the quarter",
                "tax", _dr(code("pt_expense"), due), _cr(code("pt_payable"), due),
                _dr(code("pt_payable"), withheld), _cr(code("ar"), withheld),
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
    for p in inp.filed:
        account = _paid_account(p.form)
        if account is None or p.amount <= 0 or not inp.start <= p.on <= inp.through:
            continue
        out += _kept(make_entry(
            f"tax:{p.form}:{p.year}Q{p.quarter}:paid", p.on, _book(inp, "CDJ"), p.form, ("Bureau of Internal Revenue", ""),
            f"Payment of BIR {p.form} for {p.year} Q{p.quarter}", "tax",
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
            amount = depreciation_between(a, first, last)
            out += _kept(make_entry(
                f"dep:{a.id}:{first:%Y-%m}", last, "GJ", a.doc_number, _NO_PARTY, f"Depreciation, {a.description}",
                "depreciation", _dr(code("depreciation"), amount), _cr(code("accum_dep"), amount),
            ))
    return out


def manual_entries(inp: BooksInput) -> list[Entry]:
    out: list[Entry] = []
    for m in inp.manual:
        if not inp.start <= m.on <= inp.through:
            continue
        first = m.lines[0] if m.lines else Line("")
        out += _kept(make_entry(f"je:{m.id}", m.on, m.book, m.reference, (first.party_name, first.party_tin),
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
    entries.sort(key=lambda e: (e.date, JOURNAL_BOOKS.index(e.book) if e.book in JOURNAL_BOOKS else 9, e.id))
    return entries, warnings
```

- [ ] **Step 4: Run tests**

Run: `docker compose exec -T backend python -m pytest -q tests/test_aa_books_taxes.py tests/test_aa_books_posting.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/accounting/compute/books.py backend/tests/test_aa_books_taxes.py
git commit -m "feat(accounting): post tax accruals, filed-return payments, depreciation and typed entries

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Journals, General Ledger, subsidiary ledgers and trial balance (pure)

**Files:**
- Create: `backend/app/services/accounting/compute/book_ledgers.py`
- Modify: `backend/app/services/accounting/compute/specs.py:395` (final `LEDGER_ORDER`; titles and columns)
- Test: `backend/tests/test_aa_books_ledgers.py`

**Interfaces:**
- Consumes: `Entry`, `Line` (Tasks 6–7), `Chart` (Task 1), `period_for` (`services/accounting/periods.py`).
- Produces: `BOOK_TABS = ("SJ", "PJ", "CRJ", "CDJ", "GJ", "GL", "AR", "AP", "TB")`; `entry_numbers(entries, fye) -> dict[str, str]`; `balances(entries, upto: date) -> dict[str, Decimal]` (debit − credit, entries dated ≤ upto); `build_books(entries, chart, window_start, window_end, fye, books_kept) -> dict[str, list[dict]]`; `trial_balance_totals(rows) -> tuple[Decimal, Decimal]`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_aa_books_ledgers.py
from datetime import date
from decimal import Decimal

from app.services.accounting.books.chart import Chart, default_books, standard_chart
from app.services.accounting.compute.book_ledgers import (
    BOOK_TABS, build_books, entry_numbers, trial_balance_totals,
)
from app.services.accounting.compute.books import BooksInput, Line, ManualEntry, Payment, post_all
from app.services.accounting.compute.specs import LEDGER_COLUMNS, LEDGER_ORDER
from tests.aa_factories import company, expense, sale

D = Decimal
CHART = Chart(standard_chart("corporation"))
C = CHART.code


def _entries():
    opening = ManualEntry("o", "opening", "GJ", date(2026, 7, 1), "OB", "Opening balances",
                          (Line(C("cash"), debit=D("5000")), Line(C("ar"), debit=D("1000"), party_name="Old Client"),
                           Line(C("capital"), credit=D("6000"))))
    s = sale(gross="11200", vatable="10000", vat="1200", doc_date=date(2026, 7, 5), doc_number="SI-1")
    e = expense(account="rent", gross="5600", vat="600", input_vat_valid=True, doc_date=date(2026, 7, 6),
                doc_number="B-9")
    inp = BooksInput(company(), CHART, frozenset(default_books(True)), date(2026, 7, 1), date(2026, 9, 30),
                     lines=(s, e), ewt={e.id: D("250")}, manual=(opening,),
                     payments=(Payment("p1", s.id, date(2026, 8, 1), None, "bank", "CR-1"),
                               Payment("p2", e.id, date(2026, 8, 2), None, "cash", "")))
    return post_all(inp)[0], s, e


def test_every_tab_has_columns_and_rows_carry_every_column():
    entries, _, _ = _entries()
    tabs = build_books(entries, CHART, date(2026, 7, 1), date(2026, 9, 30), 12, frozenset(default_books(True)))
    assert set(tabs) == set(BOOK_TABS)
    for name in BOOK_TABS:
        assert name in LEDGER_ORDER
        keys = {k for k, _, _ in LEDGER_COLUMNS[name]}
        for row in tabs[name]:
            assert keys <= set(row) and "key" in row, (name, row)
        assert len({r["key"] for r in tabs[name]}) == len(tabs[name]), name


def test_journal_columns():
    entries, s, e = _entries()
    tabs = build_books(entries, CHART, date(2026, 7, 1), date(2026, 9, 30), 12, frozenset(default_books(True)))
    [sj] = tabs["SJ"]
    assert (sj["reference"], sj["ar"], sj["vatable"], sj["output_vat"]) == ("SI-1", D("11200.00"), D("10000"),
                                                                         D("1200.00"))
    [pj] = tabs["PJ"]
    assert (pj["expense"], pj["input_vat"], pj["ewt"], pj["ap"]) == (D("5000.00"), D("600.00"), D("250.00"),
                                                                    D("5350.00"))
    [crj] = tabs["CRJ"]
    assert (crj["bank"], crj["ar"], crj["cash"]) == (D("11200.00"), D("11200.00"), D("0.00"))
    [cdj] = tabs["CDJ"]
    assert (cdj["cash"], cdj["ap"]) == (D("5350.00"), D("5350.00"))
    assert {r["code"] for r in tabs["GJ"]} == {C("cash"), C("ar"), C("capital")}


def test_trial_balance_balances_and_ledgers_carry_balances():
    entries, _, _ = _entries()
    tabs = build_books(entries, CHART, date(2026, 8, 1), date(2026, 9, 30), 12, frozenset(default_books(True)))
    debit, credit = trial_balance_totals(tabs["TB"])
    assert debit == credit
    ar_rows = [r for r in tabs["GL"] if r["code"] == C("ar")]
    assert ar_rows[0]["particulars"] == "Balance brought forward" and ar_rows[0]["balance"] == D("12200.00")
    assert ar_rows[-1]["balance"] == D("1000.00") and ar_rows[-1]["side"] == "Dr"
    parties = {r["party"] for r in tabs["AR"]}
    assert {"Old Client", "Customer"} <= parties


def test_books_not_kept_have_no_tab():
    entries, _, _ = _entries()
    tabs = build_books(entries, CHART, date(2026, 7, 1), date(2026, 9, 30), 12, frozenset(default_books(False)))
    assert "SJ" not in tabs and "PJ" not in tabs and "GJ" in tabs and "GL" in tabs


def test_entry_numbers_restart_each_fiscal_year():
    entries, _, _ = _entries()
    numbers = entry_numbers(entries, 12)
    assert numbers["je:o"] == "GJ-2026-P0001"
    assert all(n.startswith(("SJ-2026", "PJ-2026", "CRJ-2026", "CDJ-2026", "GJ-2026")) for n in numbers.values())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec -T backend python -m pytest -q tests/test_aa_books_ledgers.py`
Expected: FAIL — `ModuleNotFoundError: app.services.accounting.compute.book_ledgers`

- [ ] **Step 3: Implement**

```python
# backend/app/services/accounting/compute/book_ledgers.py
"""Journals, General Ledger, AR/AP subsidiary ledgers and trial balance for a date window (pure).

Rows are keyed dicts, like the other ledger tabs, so versions diff and highlight unchanged.
"""

from datetime import date
from decimal import Decimal

from app.services.accounting.books.chart import JOURNAL_BOOKS, Chart
from app.services.accounting.compute.books import Entry
from app.services.accounting.compute.money import ZERO, c2, total
from app.services.accounting.matching import normalize_name
from app.services.accounting.periods import period_for

BOOK_TABS = ("SJ", "PJ", "CRJ", "CDJ", "GJ", "GL", "AR", "AP", "TB")


def entry_numbers(entries: list[Entry], fye: int) -> dict[str, str]:
    """Provisional entry numbers per book per fiscal year (final numbers come with closing, phase 2)."""
    counters: dict[tuple[str, int], int] = {}
    out: dict[str, str] = {}
    for e in entries:
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


def _side(balance: Decimal) -> str:
    return "Dr" if balance > 0 else ("Cr" if balance < 0 else "")


def _net(e: Entry, code: str, debit_side: bool) -> Decimal:
    value = total(l.debit - l.credit for l in e.lines if l.account == code)
    return value if debit_side else c2(-value)


def _base(e: Entry, numbers: dict[str, str]) -> dict:
    return {"key": e.id, "date": e.date.isoformat(), "entry_no": numbers[e.id], "reference": e.reference,
            "party": e.party_name, "tin": e.party_tin, "particulars": e.particulars}


def _columnar(e: Entry, numbers, chart: Chart, columns: dict[str, tuple[str, bool]]) -> list[dict]:
    """One row per entry with the named columns; lines on other accounts go to Sundry (extra rows if several)."""
    row = _base(e, numbers)
    used = set()
    for name, (code, debit_side) in columns.items():
        row[name] = _net(e, code, debit_side)
        used.add(code)
    sundry = [l for l in e.lines if l.account not in used]
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


def _gl(entries, window, window_start, chart, numbers) -> list[dict]:
    before = {code: bal for code, bal in balances([e for e in entries if e.date < window_start],
                                                  window_start).items() if bal != 0}
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
    opening: dict[str, list] = {}
    for e in entries:
        if e.date >= window_start:
            continue
        for l in e.lines:
            if l.account == code:
                key, name, tin = _party(e, l)
                slot = opening.setdefault(key, [name, tin, ZERO])
                slot[2] = c2(slot[2] + l.debit - l.credit)
    activity: dict[str, list] = {}
    for e in window:
        for i, l in enumerate(e.lines):
            if l.account == code:
                key, name, tin = _party(e, l)
                activity.setdefault(key, []).append((e, i, l, name, tin))
    rows: list[dict] = []
    for key in sorted(set(opening) | set(activity), key=lambda k: (opening.get(k) or activity[k][0][3:])[0].lower()):
        name, tin, bal = opening.get(key, [activity[key][0][3], activity[key][0][4], ZERO])
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


def _tb(entries, window_end, chart) -> list[dict]:
    rows = [{"key": code, "code": code, "account": chart.name(code),
             "debit": bal if bal > 0 else ZERO, "credit": -bal if bal < 0 else ZERO}
            for code, bal in sorted(balances(entries, window_end).items()) if bal != 0]
    rows.append({"key": "~total", "code": "", "account": "Total", "debit": total(r["debit"] for r in rows),
                 "credit": total(r["credit"] for r in rows)})
    return rows


def trial_balance_totals(rows: list[dict]) -> tuple[Decimal, Decimal]:
    last = rows[-1] if rows else {"debit": ZERO, "credit": ZERO}
    return last["debit"], last["credit"]


def build_books(entries: list[Entry], chart: Chart, window_start: date, window_end: date, fye: int,
                books_kept: frozenset[str]) -> dict[str, list[dict]]:
    numbers = entry_numbers(entries, fye)
    window = [e for e in entries if window_start <= e.date <= window_end]
    tabs: dict[str, list[dict]] = {}
    for book in JOURNAL_BOOKS:
        if book == "GJ" or book in books_kept:
            tabs[book] = _journal(book, window, numbers, chart)
    tabs["GL"] = _gl(entries, window, window_start, chart, numbers)
    tabs["AR"] = _subledger(entries, window, window_start, chart.code("ar"), numbers)
    tabs["AP"] = _subledger(entries, window, window_start, chart.code("ap"), numbers)
    tabs["TB"] = _tb(entries, window_end, chart)
    return tabs
```

In `backend/app/services/accounting/compute/specs.py`, replace the final `LEDGER_ORDER = (...)` line (≈395) with:

```python
LEDGER_ORDER = ("SLS", "SLP", "SAWT", "QAP", "Depreciation", "NOLCO", "ExcessMCIT", "QuarterCredits", "Transactions",
                "SJ", "PJ", "CRJ", "CDJ", "GJ", "GL", "AR", "AP", "TB")
```

and append at the end of the file:

```python
# --- Books of accounts ------------------------------------------------------------------------

_JOURNAL_HEAD = (("date", "Date", "text"), ("entry_no", "Entry no.", "text"), ("reference", "Reference", "text"),
                 ("party", "Name", "text"), ("tin", "TIN", "text"), ("particulars", "Particulars", "text"))
_SUNDRY = (("sundry_account", "Sundry account", "text"), ("sundry_dr", "Sundry Dr", "money"),
           ("sundry_cr", "Sundry Cr", "money"))
_RUNNING = (("debit", "Debit", "money"), ("credit", "Credit", "money"), ("balance", "Balance", "money"),
            ("side", "Dr/Cr", "text"))
LEDGER_TITLES.update({
    "SJ": "Sales Journal", "PJ": "Purchase Journal", "CRJ": "Cash Receipts Journal",
    "CDJ": "Cash Disbursements Journal", "GJ": "General Journal", "GL": "General Ledger",
    "AR": "Accounts receivable ledger", "AP": "Accounts payable ledger", "TB": "Trial balance",
})
LEDGER_COLUMNS.update({
    "SJ": _JOURNAL_HEAD + (("ar", "Accounts receivable Dr", "money"), ("vatable", "VATable sales", "money"),
                           ("zero_rated", "Zero-rated sales", "money"), ("exempt", "Exempt sales", "money"),
                           ("output_vat", "Output VAT Cr", "money")),
    "PJ": _JOURNAL_HEAD + (("account", "Account", "text"), ("expense", "Purchases / expense Dr", "money"),
                           ("input_vat", "Input VAT Dr", "money"), ("ewt", "EWT payable Cr", "money"),
                           ("ap", "Accounts payable Cr", "money")),
    "CRJ": _JOURNAL_HEAD + (("cash", "Cash on hand Dr", "money"), ("bank", "Cash in bank Dr", "money"),
                            ("cwt", "CWT Dr", "money"), ("ar", "Accounts receivable Cr", "money")) + _SUNDRY,
    "CDJ": _JOURNAL_HEAD + (("cash", "Cash on hand Cr", "money"), ("bank", "Cash in bank Cr", "money"),
                            ("ap", "Accounts payable Dr", "money"), ("input_vat", "Input VAT Dr", "money"),
                            ("ewt", "EWT payable Cr", "money")) + _SUNDRY,
    "GJ": (("date", "Date", "text"), ("entry_no", "Entry no.", "text"), ("code", "Account code", "text"),
           ("account", "Account title", "text"), ("particulars", "Particulars", "text"), ("debit", "Debit", "money"),
           ("credit", "Credit", "money")),
    "GL": (("code", "Account code", "text"), ("account", "Account title", "text"), ("date", "Date", "text"),
           ("reference", "Entry no.", "text"), ("particulars", "Particulars", "text")) + _RUNNING,
    "AR": (("party", "Customer", "text"), ("tin", "TIN", "text"), ("date", "Date", "text"),
           ("reference", "Entry no.", "text"), ("particulars", "Particulars", "text")) + _RUNNING,
    "AP": (("party", "Supplier", "text"), ("tin", "TIN", "text"), ("date", "Date", "text"),
           ("reference", "Entry no.", "text"), ("particulars", "Particulars", "text")) + _RUNNING,
    "TB": (("code", "Account code", "text"), ("account", "Account title", "text"), ("debit", "Debit", "money"),
           ("credit", "Credit", "money")),
})
```

- [ ] **Step 4: Run tests**

Run: `docker compose exec -T backend python -m pytest -q tests/test_aa_books_ledgers.py tests/test_aa_xlsx.py tests/test_aa_diff.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/accounting/compute/book_ledgers.py backend/app/services/accounting/compute/specs.py backend/tests/test_aa_books_ledgers.py
git commit -m "feat(accounting): journals, general ledger, AR/AP ledgers and trial balance tabs

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Load inputs and add the books to each quarter's Generate

**Files:**
- Create: `backend/app/services/accounting/books/loader.py`
- Modify: `backend/app/routers/accounting_periods.py` (`generate_output`, `_is_stale`, `mark_filed`, the per-form filed handler)
- Modify: `backend/app/routers/accounting.py` (`get_tree` facts map)
- Test: `backend/tests/test_aa_books_loader.py`

**Interfaces:**
- Consumes: everything above; `build_quarter`, `compute_ewt`, `quarter_start`, `quarter_end`, `PAYABLE_ITEM`.
- Produces: pure `filed_payments(periods: list[tuple[int, int, dict]], outputs: dict[str, dict]) -> tuple[FiledPayment, ...]` (periods = (year, quarter, filed_forms); outputs = output id → snapshot); pure `books_warnings(tabs, inputs: PeriodInputs, has_employees: bool, chart: Chart) -> list[str]`; pure `books_window(start: date, year, quarter, fye) -> tuple[date, date] | None`; async `ensure_chart(db, company) -> Chart`; async `quarter_books(db, company, facts, year, quarter, result, assets, periods) -> tuple[dict[str, list[dict]], list[str]]`; `touch_books(company)` (sets `books_updated_at`).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_aa_books_loader.py
from datetime import date, datetime, timezone
from decimal import Decimal

from app.services.accounting.books.chart import Chart, standard_chart
from app.services.accounting.books.loader import books_warnings, books_window, filed_payments
from app.services.accounting.compute.inputs import PeriodInputs

D = Decimal
CHART = Chart(standard_chart("corporation"))


def test_filed_payments_read_the_payable_of_the_filed_version_in_manila_time():
    filed = {"2550Q": {"output_id": "o1", "version": 2, "filed_at": "2026-10-24T17:30:00+00:00"},
             "1702RT": {"output_id": "o2", "version": 1, "filed_at": "2026-04-10T01:00:00+00:00"}}
    outputs = {"o1": {"forms": {"2550Q": {"26": "1234.50"}}}}
    [p] = filed_payments([(2026, 3, filed)], outputs)
    assert (p.form, p.year, p.quarter, p.on, p.amount) == ("2550Q", 2026, 3, date(2026, 10, 25), D("1234.50"))


def test_filed_payments_skip_missing_outputs_and_annual():
    assert filed_payments([(2026, 3, {"2550Q": {"output_id": "gone", "version": 1,
                                                "filed_at": "2026-10-20T00:00:00+00:00"}})], {}) == ()
    assert filed_payments([(2026, 0, {"1702RT": {"output_id": "o", "version": 1,
                                                 "filed_at": "2027-04-10T00:00:00+00:00"}})],
                          {"o": {"forms": {"1702RT": {"21": "5"}}}}) == ()


def test_books_window():
    assert books_window(date(2026, 8, 15), 2026, 3, 12) == (date(2026, 8, 15), date(2026, 9, 30))
    assert books_window(date(2026, 1, 1), 2026, 3, 12) == (date(2026, 7, 1), date(2026, 9, 30))
    assert books_window(date(2026, 10, 1), 2026, 3, 12) is None


def test_books_warnings():
    tb_off = {"TB": [{"key": "~total", "debit": D("10"), "credit": D("9")}], "GL": []}
    warnings = books_warnings(tb_off, PeriodInputs(non_operating_income=D("500")), True, CHART)
    assert any("trial balance doesn't balance" in w for w in warnings)
    assert any("Other income of ₱500.00" in w for w in warnings)
    assert any("SSS / PhilHealth / Pag-IBIG" in w for w in warnings)
    ok = {"TB": [{"key": "~total", "debit": D("9"), "credit": D("9")}],
          "GL": [{"code": "2170", "credit": D("1"), "debit": D("0")}, {"code": "4100", "credit": D("500"),
                                                                       "debit": D("0")}]}
    assert books_warnings(ok, PeriodInputs(non_operating_income=D("500")), True, CHART) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec -T backend python -m pytest -q tests/test_aa_books_loader.py`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement the loader**

```python
# backend/app/services/accounting/books/loader.py
"""Gather what the books need for one quarter and build the book tabs (async loader + pure helpers)."""

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.accounting import AAAccount, AACompany, AADocument, AAJournalEntry, AAOutput, AAPeriod
from app.services.accounting.books.chart import Chart, ChartAccount, default_books, missing_standard, standard_chart
from app.services.accounting.compute.book_ledgers import build_books, trial_balance_totals
from app.services.accounting.compute.books import (
    BooksInput, FiledPayment, Line, ManualEntry, Payment, QuarterTaxes, post_all,
)
from app.services.accounting.compute.due_dates import quarter_end, quarter_start
from app.services.accounting.compute.engine import QuarterResult, build_quarter
from app.services.accounting.compute.ewt import compute_ewt
from app.services.accounting.compute.inputs import CompanyFacts, PeriodData, PeriodInputs
from app.services.accounting.compute.money import ZERO, c2
from app.services.accounting.compute.specs import PAYABLE_ITEM

_MANILA = ZoneInfo("Asia/Manila")


def touch_books(company: AACompany) -> None:
    """Book tabs generated before now are stale (chart, journal entries or filed returns changed)."""
    company.books_updated_at = datetime.now(timezone.utc)


def books_window(start: date, year: int, quarter: int, fye: int) -> tuple[date, date] | None:
    first, last = quarter_start(year, quarter, fye), quarter_end(year, quarter, fye)
    if last < start:
        return None
    return max(first, start), last


def filed_payments(periods: list[tuple[int, int, dict]], outputs: dict[str, dict]) -> tuple[FiledPayment, ...]:
    out: list[FiledPayment] = []
    for year, quarter, filed in periods:
        if quarter == 0:  # annual returns are posted in phase 3
            continue
        for form, entry in (filed or {}).items():
            item = PAYABLE_ITEM.get(form)
            snap = outputs.get(str(entry.get("output_id")))
            value = (snap or {}).get("forms", {}).get(form, {}).get(item) if item else None
            try:
                amount = c2(value)
                on = datetime.fromisoformat(entry["filed_at"]).astimezone(_MANILA).date()
            except (InvalidOperation, TypeError, ValueError, KeyError):
                continue
            out.append(FiledPayment(form, year, quarter, on, amount))
    return tuple(out)


def _gl_activity(tabs: dict, code: str) -> bool:
    return any(r.get("code") == code and (r.get("debit") or r.get("credit")) for r in tabs.get("GL", []))


def books_warnings(tabs: dict, inputs: PeriodInputs, has_employees: bool, chart: Chart) -> list[str]:
    warnings: list[str] = []
    debit, credit = trial_balance_totals(tabs.get("TB", []))
    if debit != credit:
        warnings.append(f"The trial balance doesn't balance (debits ₱{debit:,.2f}, credits ₱{credit:,.2f}). "
                        "This is a bug: report it before relying on these books.")
    if inputs.non_operating_income > 0 and not _gl_activity(tabs, chart.code("other_income")):
        warnings.append(f"Other income of ₱{inputs.non_operating_income:,.2f} is in the quarter inputs but not in "
                        "the books. Post it as a journal entry in Books.")
    contributions = next((a.code for a in chart.accounts if a.code == "2170"), None)
    if has_employees and contributions and not _gl_activity(tabs, contributions):
        warnings.append("SSS / PhilHealth / Pag-IBIG contributions aren't in the documents. Post the employer and "
                        "employee shares as journal entries in Books.")
    return warnings


def _chart_account(row: AAAccount) -> ChartAccount:
    return ChartAccount(row.code, row.name, row.type, row.contra, row.system_key, row.parent_code, row.active)


async def ensure_chart(db: AsyncSession, company: AACompany) -> Chart:
    """The company's chart, seeding the standard accounts that are missing (first use or newer keys)."""
    rows = (await db.execute(select(AAAccount).where(AAAccount.company_id == company.id))).scalars().all()
    missing = (standard_chart(company.taxpayer_type) if not rows
               else missing_standard([_chart_account(r) for r in rows], company.taxpayer_type))
    if missing:
        await db.execute(pg_insert(AAAccount).values([
            dict(id=uuid.uuid4(), enterprise_id=company.enterprise_id, company_id=company.id, code=a.code,
                 name=a.name, type=a.type, contra=a.contra, parent_code=a.parent_code, system_key=a.system_key,
                 active=True, created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc))
            for a in missing
        ]).on_conflict_do_nothing())
        rows = (await db.execute(select(AAAccount).where(AAAccount.company_id == company.id))).scalars().all()
    return Chart(_chart_account(r) for r in rows)


def _manual(row: AAJournalEntry) -> ManualEntry:
    lines = tuple(Line(str(x.get("account_code", "")), c2(x.get("debit") or 0), c2(x.get("credit") or 0),
                       str(x.get("party_name", "")), str(x.get("party_tin", ""))) for x in row.lines or [])
    return ManualEntry(str(row.id), row.kind, row.book, row.entry_date, row.reference, row.particulars, lines)


async def quarter_books(db: AsyncSession, company: AACompany, facts: CompanyFacts, year: int, quarter: int,
                        result: QuarterResult, assets, periods: list[PeriodData]) -> tuple[dict, list[str]]:
    """Book tabs for the quarter being generated ({} when books are off or start after this quarter)."""
    from app.routers.accounting_periods import doc_line, supplier_atc_rules, supplier_gl_rules  # router imports us

    fye = company.fiscal_year_end_month
    if company.books_start is None:
        return {}, []
    window = books_window(company.books_start, year, quarter, fye)
    if window is None:
        return {}, []
    through = window[1]
    chart = await ensure_chart(db, company)

    docs = (await db.execute(select(AADocument).where(
        AADocument.company_id == company.id, AADocument.deleted_at.is_(None), AADocument.excluded.is_(False),
        AADocument.doc_date.is_not(None), AADocument.doc_date <= through,
    ))).scalars().all()
    atc_rules, gl_rules = await supplier_atc_rules(db, company.id), await supplier_gl_rules(db, company.id)
    receipts = [d for d in docs if d.settles_document_id is not None]
    posted = [d for d in docs if d.settles_document_id is None]
    lines = tuple(doc_line(d, atc_rules, gl_rules) for d in posted)
    paid_by_receipt = {str(r.settles_document_id) for r in receipts}
    payments = [Payment(f"rcpt:{r.id}", str(r.settles_document_id), r.doc_date, r.gross_amount,
                        r.paid_via or "cash", r.doc_number) for r in receipts]
    payments += [Payment(f"paid:{d.id}", str(d.id), d.paid_on, None, d.paid_via or "cash", d.payment_ref)
                 for d in posted if d.paid_on is not None and str(d.id) not in paid_by_receipt]
    ewt = {line_id: tax for line_id, (_, tax) in compute_ewt(lines, facts, year, quarter).by_line().items()}

    quarters = []
    for i, p in enumerate(periods):
        forms = result.forms if (p.year, p.quarter) == (year, quarter) else build_quarter(
            facts, periods[: i + 1], assets=assets).forms
        quarters.append(QuarterTaxes(p.year, p.quarter, quarter_end(p.year, p.quarter, fye), forms))

    rows = (await db.execute(select(AAPeriod.year, AAPeriod.quarter, AAPeriod.filed_forms).where(
        AAPeriod.company_id == company.id))).all()
    ids = {uuid.UUID(str(e["output_id"])) for _, _, f in rows for e in (f or {}).values() if e.get("output_id")}
    outputs = {str(o.id): o.snapshot for o in (await db.execute(
        select(AAOutput).where(AAOutput.id.in_(ids)))).scalars().all()} if ids else {}
    manual = (await db.execute(select(AAJournalEntry).where(
        AAJournalEntry.company_id == company.id, AAJournalEntry.deleted_at.is_(None),
        AAJournalEntry.entry_date <= through,
    ))).scalars().all()

    kept = frozenset(company.books_kept or default_books(facts.vat_registered)) | {"GJ"}
    inp = BooksInput(facts, chart, kept, company.books_start, through, lines=lines, ewt=ewt,
                     payments=tuple(payments), manual=tuple(_manual(m) for m in manual), quarters=tuple(quarters),
                     filed=filed_payments([tuple(r) for r in rows], outputs), assets=tuple(assets))
    entries, warnings = post_all(inp)
    tabs = build_books(entries, chart, window[0], through, fye, kept)
    target_inputs = periods[-1].inputs if periods else PeriodInputs()
    return tabs, warnings + books_warnings(tabs, target_inputs, company.has_employees, chart)
```

- [ ] **Step 4: Wire it into Generate and staleness**

In `backend/app/routers/accounting_periods.py` (imports: `from app.services.accounting.books.loader import quarter_books, touch_books`), change `generate_output`:

```python
    periods = await load_periods(db, company, year, quarter)
    result = build_quarter(facts, periods, amended=amends_payment(filed),
                           assets=assets, filed_remittances=await _remittances(db, filed))
    book_tabs, book_warnings = await quarter_books(db, company, facts, year, quarter, result, assets, periods)
    result.ledgers.update(book_tabs)
    result.warnings.extend(book_warnings)
    snap = snapshot(result, facts)
```

In `_is_stale`, include the books timestamp:

```python
    books_change = company.books_updated_at if company.books_start is not None else None
    return any(t is not None and t > generated_at
               for t in (doc_change, input_change, asset_change, company.facts_updated_at, books_change))
```

In `mark_filed` and in the per-form filed handler (`PUT /periods/{company_id}/{year}/{quarter}/filed-forms/{form}`), right before `await db.commit()`, add:

```python
    company = await db.get(AACompany, period.company_id)
    if company is not None and company.books_start is not None:
        touch_books(company)  # a filed return posts its payment in the books
```

(If `mark_filed` doesn't receive the company, fetch it via `db.get(AACompany, period.company_id)` as shown; `AACompany` is already imported.)

In `backend/app/routers/accounting.py::get_tree`, replace the `facts` dict:

```python
    facts = {}
    for c in companies:
        times = [t for t in (c.facts_updated_at, c.books_updated_at if c.books_start else None) if t is not None]
        if times:
            facts[str(c.id)] = max(times)
```

- [ ] **Step 5: Run the backend suite**

Run: `docker compose exec -T backend python -m pytest -q tests/test_aa_books_loader.py tests/ -k "aa_ or accounting"`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/accounting/books/loader.py backend/app/routers/accounting_periods.py backend/app/routers/accounting.py backend/tests/test_aa_books_loader.py
git commit -m "feat(accounting): books tabs in each quarter's Generate

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Books API — chart, journal entries, document payments, company settings

**Files:**
- Create: `backend/app/schemas/accounting_books.py`
- Create: `backend/app/routers/accounting_books.py`
- Modify: `backend/app/routers/accounting.py` (include the router before `accounting_annual`)
- Modify: `backend/app/schemas/accounting.py` (`CompanyIn` books fields + defaults; `TreeCompanyOut.books_start`)
- Modify: `backend/app/services/accounting/tree.py` (`TreeCompanyInput.books_start`, output key)
- Modify: `backend/app/routers/accounting.py::get_tree` (pass `c.books_start`)
- Test: `backend/tests/test_aa_books_api.py`

**Interfaces:**
- Consumes: `ensure_chart`, `touch_books` (Task 9), `candidates_for`, `doc_ref`, `invoice_docs` (Tasks 3, 5).
- Produces: routes `GET/POST /companies/{company_id}/accounts`, `PATCH /accounts/{account_id}`, `GET/POST /companies/{company_id}/journal-entries`, `PUT/DELETE /journal-entries/{entry_id}`, `GET /documents/{doc_id}/payments`; schemas `AccountOut`, `AccountIn`, `AccountPatch`, `JournalLineIn`, `JournalEntryIn`, `JournalEntryOut`, `DocRefOut`, `PaymentLinksOut`; `CompanyIn.books_start: date | None`, `books_kept: list[str]`, `books_signatory: str`, `books_signatory_title: str`; tree company key `books_start`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_aa_books_api.py
from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.accounting import CompanyIn
from app.schemas.accounting_books import AccountIn, JournalEntryIn
from tests.test_accounting_annual_routes import _endpoint

LINES = [{"account_code": "1010", "debit": "500"}, {"account_code": "3010", "credit": "500"}]


def test_journal_entry_must_balance_and_lines_are_one_sided():
    e = JournalEntryIn(entry_date=date(2026, 7, 1), lines=LINES)
    assert e.kind == "manual" and e.book == "GJ" and e.lines[0].debit == Decimal("500")
    with pytest.raises(ValidationError, match="balance"):
        JournalEntryIn(entry_date=date(2026, 7, 1), lines=[LINES[0], {"account_code": "3010", "credit": "400"}])
    with pytest.raises(ValidationError):
        JournalEntryIn(entry_date=date(2026, 7, 1),
                       lines=[{"account_code": "1010", "debit": "5", "credit": "5"}, LINES[1]])
    with pytest.raises(ValidationError):
        JournalEntryIn(entry_date=date(2026, 7, 1), lines=[LINES[0]])
    with pytest.raises(ValidationError):
        JournalEntryIn(kind="opening", book="CRJ", entry_date=date(2026, 7, 1), lines=LINES)


def test_account_codes_are_digits():
    assert AccountIn(code="6021", name="Rent - warehouse", parent_code="6020").code == "6021"
    with pytest.raises(ValidationError):
        AccountIn(code="60-21", name="x", parent_code="6020")


def test_company_books_defaults_follow_vat_status():
    vat = CompanyIn(registered_name="A", tin="123456789", vat_status="vat")
    non = CompanyIn(registered_name="A", tin="123456789", vat_status="non_vat", books_kept=["CRJ"])
    assert vat.books_kept == ["SJ", "PJ", "CRJ", "CDJ", "GJ", "GL"]
    assert non.books_kept == ["CRJ", "GJ", "GL"]   # GJ and GL are always kept
    with pytest.raises(ValidationError):
        CompanyIn(registered_name="A", tin="123456789", books_kept=["XYZ"])


def test_routes_resolve():
    cid = "6a1c2f40-0000-4000-8000-000000000000"
    assert _endpoint("GET", f"/companies/{cid}/accounts") == "list_accounts"
    assert _endpoint("POST", f"/companies/{cid}/accounts") == "add_account"
    assert _endpoint("PATCH", f"/accounts/{cid}") == "patch_account"
    assert _endpoint("GET", f"/companies/{cid}/journal-entries") == "list_journal_entries"
    assert _endpoint("POST", f"/companies/{cid}/journal-entries") == "create_journal_entry"
    assert _endpoint("PUT", f"/journal-entries/{cid}") == "update_journal_entry"
    assert _endpoint("DELETE", f"/journal-entries/{cid}") == "delete_journal_entry"
    assert _endpoint("GET", f"/documents/{cid}/payments") == "document_payments"
    assert _endpoint("GET", f"/documents/{cid}") == "get_document"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec -T backend python -m pytest -q tests/test_aa_books_api.py`
Expected: FAIL — `ModuleNotFoundError: app.schemas.accounting_books`

- [ ] **Step 3: Schemas**

```python
# backend/app/schemas/accounting_books.py
"""Request/response models for the books of accounts endpoints."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_MONEY = dict(default=Decimal("0"), ge=0, max_digits=14, decimal_places=2)


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    type: str
    contra: bool
    parent_code: str | None
    system_key: str | None
    active: bool


class AccountIn(BaseModel):
    code: str = Field(pattern=r"^\d{4,10}$")
    name: str = Field(min_length=1, max_length=120)
    parent_code: str = Field(pattern=r"^\d{4,10}$")


class AccountPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    active: bool | None = None


class JournalLineIn(BaseModel):
    account_code: str = Field(min_length=1, max_length=10)
    debit: Decimal = Field(**_MONEY)
    credit: Decimal = Field(**_MONEY)
    party_name: str = Field(default="", max_length=255)
    party_tin: str = Field(default="", max_length=9)

    @model_validator(mode="after")
    def _one_side(self):
        if (self.debit > 0) == (self.credit > 0):
            raise ValueError("Each line needs either a debit or a credit")
        return self


class JournalEntryIn(BaseModel):
    kind: Literal["opening", "manual"] = "manual"
    book: Literal["GJ", "CRJ", "CDJ"] = "GJ"
    entry_date: date
    reference: str = Field(default="", max_length=60)
    particulars: str = Field(default="", max_length=255)
    lines: list[JournalLineIn] = Field(min_length=2, max_length=200)

    @field_validator("reference", "particulars")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    @model_validator(mode="after")
    def _balanced(self):
        debit = sum((l.debit for l in self.lines), Decimal("0"))
        credit = sum((l.credit for l in self.lines), Decimal("0"))
        if debit != credit:
            raise ValueError(f"Debits ({debit:,.2f}) and credits ({credit:,.2f}) must balance")
        if self.kind == "opening" and self.book != "GJ":
            raise ValueError("The opening balances go in the General Journal")
        return self


class JournalEntryOut(BaseModel):
    id: uuid.UUID
    kind: str
    book: str
    entry_date: date
    reference: str
    particulars: str
    lines: list[JournalLineIn]
    created_at: datetime


class DocRefOut(BaseModel):
    id: uuid.UUID
    doc_number: str
    doc_date: date | None
    counterparty: str
    gross_amount: Decimal


class PaymentLinksOut(BaseModel):
    linked_invoice: DocRefOut | None
    candidates: list[DocRefOut]
    paid_by: list[DocRefOut]
```

In `backend/app/schemas/accounting.py`, add to `CompanyIn` (after `taxpayer_classification`) and a validator; import `default_books` from `app.services.accounting.books.chart`:

```python
    books_start: date | None = None
    books_kept: list[Literal["SJ", "PJ", "CRJ", "CDJ", "GJ", "GL"]] = Field(default_factory=list)
    books_signatory: str = Field(default="", max_length=120)
    books_signatory_title: str = Field(default="", max_length=60)
```

```python
    @model_validator(mode="after")
    def _books_kept(self):
        kept = self.books_kept or default_books(self.vat_status == "vat")
        order = ("SJ", "PJ", "CRJ", "CDJ", "GJ", "GL")
        self.books_kept = [b for b in order if b in set(kept) | {"GJ", "GL"}]
        return self
```

Add `books_start: date | None = None` to `TreeCompanyOut`.

In `backend/app/services/accounting/tree.py`: add `books_start: date | None = None` as the last field of `TreeCompanyInput` (import `date`), and `"books_start": c.books_start,` in the `out.append({...})` dict. In `get_tree`, build inputs with `TreeCompanyInput(str(c.id), c.registered_name, c.tin, c.pinned, c.fiscal_year_end_month, c.books_start)`.

- [ ] **Step 4: Router**

```python
# backend/app/routers/accounting_books.py
"""Books of accounts: chart of accounts, typed journal entries and document payment links."""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.accounting import AAAccount, AACompany, AADocument, AAJournalEntry
from app.models.user import User
from app.routers.accounting_scope import MANAGER_ROLES, company_or_404, scope_for
from app.schemas.accounting_books import (
    AccountIn, AccountOut, AccountPatch, DocRefOut, JournalEntryIn, JournalEntryOut, PaymentLinksOut,
)
from app.services.accounting.books.links import doc_ref, invoice_docs, receipt_docs
from app.services.accounting.books.loader import ensure_chart, touch_books
from app.services.accounting.books.receipts import candidates_for
from app.services.accounting.compute.depreciation import fiscal_year_window

router = APIRouter()


def _require_manager(user: User) -> None:
    if user.role not in MANAGER_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only owners and managers can change the chart of accounts")


async def _account_or_404(db: AsyncSession, ent: uuid.UUID, account_id: uuid.UUID) -> AAAccount:
    row = (await db.execute(select(AAAccount).where(AAAccount.id == account_id, AAAccount.enterprise_id == ent))
           ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Account not found")
    return row


@router.get("/companies/{company_id}/accounts", response_model=list[AccountOut])
async def list_accounts(company_id: uuid.UUID, user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    company = await company_or_404(db, scope_for(user), company_id)
    await ensure_chart(db, company)
    await db.commit()
    return (await db.execute(select(AAAccount).where(AAAccount.company_id == company.id)
                             .order_by(AAAccount.code))).scalars().all()


@router.post("/companies/{company_id}/accounts", response_model=AccountOut, status_code=status.HTTP_201_CREATED)
async def add_account(company_id: uuid.UUID, body: AccountIn, user: User = Depends(get_current_user),
                      db: AsyncSession = Depends(get_db)):
    ent = scope_for(user)
    _require_manager(user)
    company = await company_or_404(db, ent, company_id)
    await ensure_chart(db, company)
    parent = (await db.execute(select(AAAccount).where(
        AAAccount.company_id == company.id, AAAccount.code == body.parent_code))).scalar_one_or_none()
    if parent is None or not parent.active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Account {body.parent_code} isn't an active account")
    row = AAAccount(enterprise_id=ent, company_id=company.id, code=body.code, name=body.name.strip(),
                    type=parent.type, contra=parent.contra, parent_code=parent.code, active=True)
    db.add(row)
    touch_books(company)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, f"Account code {body.code} is already in the chart")
    return row


@router.patch("/accounts/{account_id}", response_model=AccountOut)
async def patch_account(account_id: uuid.UUID, body: AccountPatch, user: User = Depends(get_current_user),
                        db: AsyncSession = Depends(get_db)):
    ent = scope_for(user)
    _require_manager(user)
    row = await _account_or_404(db, ent, account_id)
    company = await company_or_404(db, ent, row.company_id)
    if body.name is not None:
        row.name = body.name.strip()
    if body.active is False and row.active:
        if row.system_key:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Posting uses this account; it can be renamed but not "
                                                             "deactivated")
        used = (await db.execute(select(AAJournalEntry.id).where(
            AAJournalEntry.company_id == company.id, AAJournalEntry.deleted_at.is_(None),
            AAJournalEntry.lines.contains([{"account_code": row.code}])).limit(1))).first() or \
            (await db.execute(select(AADocument.id).where(
                AADocument.company_id == company.id, AADocument.deleted_at.is_(None),
                AADocument.gl_account_code == row.code).limit(1))).first()
        if used:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "This account is used by journal entries or documents; "
                                                             "move them to another account first")
    if body.active is not None:
        row.active = body.active
    touch_books(company)
    await db.commit()
    return row


def _entry_out(row: AAJournalEntry) -> JournalEntryOut:
    return JournalEntryOut(id=row.id, kind=row.kind, book=row.book, entry_date=row.entry_date,
                           reference=row.reference, particulars=row.particulars, lines=row.lines,
                           created_at=row.created_at)


async def _check_entry(db: AsyncSession, company: AACompany, body: JournalEntryIn,
                       entry_id: uuid.UUID | None = None) -> None:
    if company.books_start is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Set the books start date on the company first")
    if body.kind == "opening":
        clash = (await db.execute(select(AAJournalEntry.id).where(
            AAJournalEntry.company_id == company.id, AAJournalEntry.kind == "opening",
            AAJournalEntry.deleted_at.is_(None), AAJournalEntry.id != (entry_id or uuid.uuid4())))).first()
        if clash:
            raise HTTPException(status.HTTP_409_CONFLICT, "This company already has opening balances; edit them")
    elif body.entry_date < company.books_start:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"The books start on {company.books_start:%b %d, %Y}; date the entry on or after it")
    chart = await ensure_chart(db, company)
    bad = sorted({l.account_code for l in body.lines
                  if chart.get(l.account_code) is None or not chart.get(l.account_code).active})
    if bad:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Not active accounts in the chart: {', '.join(bad)}")


def _lines_json(body: JournalEntryIn) -> list[dict]:
    return [{"account_code": l.account_code, "debit": str(l.debit), "credit": str(l.credit),
             "party_name": l.party_name.strip(), "party_tin": l.party_tin.strip()} for l in body.lines]


@router.get("/companies/{company_id}/journal-entries", response_model=list[JournalEntryOut])
async def list_journal_entries(company_id: uuid.UUID, year: int = Query(ge=2000, le=2100),
                               user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    company = await company_or_404(db, scope_for(user), company_id)
    start, end = fiscal_year_window(year, company.fiscal_year_end_month)
    rows = (await db.execute(select(AAJournalEntry).where(
        AAJournalEntry.company_id == company.id, AAJournalEntry.deleted_at.is_(None),
        AAJournalEntry.entry_date >= start, AAJournalEntry.entry_date <= end,
    ).order_by(AAJournalEntry.entry_date, AAJournalEntry.created_at))).scalars().all()
    return [_entry_out(r) for r in rows]


@router.post("/companies/{company_id}/journal-entries", response_model=JournalEntryOut,
             status_code=status.HTTP_201_CREATED)
async def create_journal_entry(company_id: uuid.UUID, body: JournalEntryIn, user: User = Depends(get_current_user),
                               db: AsyncSession = Depends(get_db)):
    ent = scope_for(user)
    company = await company_or_404(db, ent, company_id)
    await _check_entry(db, company, body)
    row = AAJournalEntry(enterprise_id=ent, company_id=company.id, kind=body.kind, book=body.book,
                         entry_date=company.books_start if body.kind == "opening" else body.entry_date,
                         reference=body.reference, particulars=body.particulars or (
                             "Opening balances" if body.kind == "opening" else ""),
                         lines=_lines_json(body), created_by=user.id)
    db.add(row)
    touch_books(company)
    await db.commit()
    return _entry_out(row)


async def _entry_or_404(db: AsyncSession, ent: uuid.UUID, entry_id: uuid.UUID) -> AAJournalEntry:
    row = (await db.execute(select(AAJournalEntry).where(
        AAJournalEntry.id == entry_id, AAJournalEntry.enterprise_id == ent, AAJournalEntry.deleted_at.is_(None),
    ))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Journal entry not found")
    return row


@router.put("/journal-entries/{entry_id}", response_model=JournalEntryOut)
async def update_journal_entry(entry_id: uuid.UUID, body: JournalEntryIn, user: User = Depends(get_current_user),
                               db: AsyncSession = Depends(get_db)):
    ent = scope_for(user)
    row = await _entry_or_404(db, ent, entry_id)
    company = await company_or_404(db, ent, row.company_id)
    await _check_entry(db, company, body, entry_id=row.id)
    row.kind, row.book, row.reference, row.particulars = body.kind, body.book, body.reference, body.particulars
    row.entry_date = company.books_start if body.kind == "opening" else body.entry_date
    row.lines = _lines_json(body)
    touch_books(company)
    await db.commit()
    return _entry_out(row)


@router.delete("/journal-entries/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_journal_entry(entry_id: uuid.UUID, user: User = Depends(get_current_user),
                               db: AsyncSession = Depends(get_db)):
    ent = scope_for(user)
    row = await _entry_or_404(db, ent, entry_id)
    company = await company_or_404(db, ent, row.company_id)
    row.deleted_at = datetime.now(timezone.utc)
    touch_books(company)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _ref(doc: AADocument) -> DocRefOut:
    name = doc.buyer_name if doc.client_role == "seller" else doc.seller_name
    return DocRefOut(id=doc.id, doc_number=doc.doc_number, doc_date=doc.doc_date, counterparty=name,
                     gross_amount=doc.gross_amount)


@router.get("/documents/{doc_id}/payments", response_model=PaymentLinksOut)
async def document_payments(doc_id: uuid.UUID, user: User = Depends(get_current_user),
                            db: AsyncSession = Depends(get_db)):
    ent = scope_for(user)
    doc = (await db.execute(select(AADocument).where(
        AADocument.id == doc_id, AADocument.enterprise_id == ent, AADocument.deleted_at.is_(None)))
           ).scalar_one_or_none()
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    docs = (await db.execute(select(AADocument).where(
        AADocument.company_id == doc.company_id, AADocument.deleted_at.is_(None)))).scalars().all()
    by_id = {d.id: d for d in docs}
    linked = by_id.get(doc.settles_document_id) if doc.settles_document_id else None
    candidates: list[AADocument] = []
    if doc in receipt_docs(docs):
        taken = {str(d.settles_document_id) for d in docs if d.settles_document_id and d.id != doc.id}
        ids = set(candidates_for(doc_ref(doc), [doc_ref(i) for i in invoice_docs(docs)], taken))
        candidates = [d for d in docs if str(d.id) in ids]
    paid_by = [d for d in docs if d.settles_document_id == doc.id]
    return PaymentLinksOut(linked_invoice=_ref(linked) if linked else None,
                           candidates=[_ref(d) for d in candidates], paid_by=[_ref(d) for d in paid_by])
```

In `backend/app/routers/accounting.py`, import `accounting_books` alongside the other sub-routers and include it **before** the annual and period routers:

```python
router.include_router(accounting_books.router)
# Annual routes first: "/periods/{company}/{year}/annual" would otherwise match the quarter route's {quarter}.
router.include_router(accounting_annual.router)
router.include_router(accounting_periods.router)
```

(`/documents/{doc_id}/payments` and `/documents/{doc_id}` don't overlap, so mounting order against `get_document` doesn't matter.)

- [ ] **Step 5: Run tests**

Run: `docker compose exec -T backend python -m pytest -q tests/test_aa_books_api.py tests/test_accounting_tree.py tests/test_accounting_schemas.py tests/test_accounting_annual_routes.py`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/schemas/accounting_books.py backend/app/routers/accounting_books.py backend/app/routers/accounting.py backend/app/schemas/accounting.py backend/app/services/accounting/tree.py backend/tests/test_aa_books_api.py
git commit -m "feat(accounting): chart, journal entry and payment-link endpoints; books settings on companies

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Frontend — types, API client, company books settings, document payments

**Files:**
- Modify: `frontend/src/types/accounting.ts`
- Modify: `frontend/src/lib/accounting-api.ts`
- Modify: `frontend/src/lib/accounting-format.ts` (`REASON_LABELS.possible_payment`, `BOOK_LABELS`)
- Modify: `frontend/src/components/accounting/CompanyForm.tsx`
- Modify: `frontend/src/components/accounting/DocumentPanel.tsx`

**Interfaces:**
- Consumes: endpoints from Task 10, document fields from Task 4.
- Produces: TS types `Account`, `JournalLine`, `JournalEntry`, `JournalEntryInput`, `DocRef`, `PaymentLinks`; `accountingApi.accounts/addAccount/updateAccount/journalEntries/createJournalEntry/updateJournalEntry/deleteJournalEntry/documentPayments`; `BOOK_LABELS`.

- [ ] **Step 1: Types** — in `frontend/src/types/accounting.ts`, add to `CompanyInput`:

```ts
  /** First day on the books (YYYY-MM-DD); null = books off. */
  books_start: string | null;
  books_kept: string[];
  books_signatory: string;
  books_signatory_title: string;
```

add to `AADocument`:

```ts
  paid_on: string | null;
  paid_via: "" | "cash" | "bank" | "ewallet";
  payment_ref: string;
  settles_document_id: string | null;
  settles_source: "" | "auto" | "user";
  gl_account_code: string;
```

add `books_start: string | null;` to `TreeCompany`, `view?: "books";` to `FolderRef`, and these new types at the end:

```ts
export interface Account {
  id: string;
  code: string;
  name: string;
  type: "asset" | "liability" | "equity" | "income" | "cost" | "expense";
  contra: boolean;
  parent_code: string | null;
  system_key: string | null;
  active: boolean;
}

export interface JournalLine {
  account_code: string;
  debit: string;
  credit: string;
  party_name: string;
  party_tin: string;
}

export interface JournalEntryInput {
  kind: "opening" | "manual";
  book: "GJ" | "CRJ" | "CDJ";
  entry_date: string;
  reference: string;
  particulars: string;
  lines: JournalLine[];
}

export interface JournalEntry extends JournalEntryInput {
  id: string;
  created_at: string;
}

export interface DocRef {
  id: string;
  doc_number: string;
  doc_date: string | null;
  counterparty: string;
  gross_amount: string;
}

export interface PaymentLinks {
  linked_invoice: DocRef | null;
  candidates: DocRef[];
  paid_by: DocRef[];
}
```

- [ ] **Step 2: API client** — add the new types to the import list and these methods to `accountingApi`:

```ts
  accounts: (companyId: string) =>
    api.get<Account[]>(`/accounting/companies/${companyId}/accounts`).then((r) => r.data),
  addAccount: (companyId: string, data: { code: string; name: string; parent_code: string }) =>
    api.post<Account>(`/accounting/companies/${companyId}/accounts`, data).then((r) => r.data),
  updateAccount: (id: string, patch: { name?: string; active?: boolean }) =>
    api.patch<Account>(`/accounting/accounts/${id}`, patch).then((r) => r.data),
  journalEntries: (companyId: string, year: number) =>
    api
      .get<JournalEntry[]>(`/accounting/companies/${companyId}/journal-entries`, { params: { year } })
      .then((r) => r.data),
  createJournalEntry: (companyId: string, data: JournalEntryInput) =>
    api.post<JournalEntry>(`/accounting/companies/${companyId}/journal-entries`, data).then((r) => r.data),
  updateJournalEntry: (id: string, data: JournalEntryInput) =>
    api.put<JournalEntry>(`/accounting/journal-entries/${id}`, data).then((r) => r.data),
  deleteJournalEntry: (id: string) => api.delete(`/accounting/journal-entries/${id}`).then(() => undefined),
  documentPayments: (docId: string) =>
    api.get<PaymentLinks>(`/accounting/documents/${docId}/payments`).then((r) => r.data),
```

- [ ] **Step 3: Labels** — in `frontend/src/lib/accounting-format.ts` add to `REASON_LABELS`:

```ts
  possible_payment: "Looks like a payment receipt for one of several invoices. Choose the invoice it pays.",
```

and export:

```ts
export const BOOK_LABELS: Record<string, string> = {
  SJ: "Sales Journal",
  PJ: "Purchase Journal",
  CRJ: "Cash Receipts Journal",
  CDJ: "Cash Disbursements Journal",
  GJ: "General Journal",
  GL: "General Ledger",
};
```

- [ ] **Step 4: Company form** — in `CompanyForm.tsx` add to `EMPTY`:

```ts
  books_start: null,
  books_kept: [],
  books_signatory: "",
  books_signatory_title: "",
```

and, after the block that renders `check("has_employees", "Has employees")` (keep the surrounding grid), add a Books section:

```tsx
          <fieldset className="col-span-2 mt-2 rounded-lg border border-[var(--border)] p-3">
            <legend className="px-1 text-xs font-semibold text-[var(--text-secondary)]">Books of accounts</legend>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className={LABEL}>Books start</label>
                <input
                  type="date"
                  className={INPUT}
                  value={form.books_start ?? ""}
                  onChange={(e) => set("books_start", e.target.value || null)}
                />
                <span className="mt-0.5 block text-[11px] text-[var(--text-secondary)]">
                  Leave empty to keep returns only. Enter the opening balances as of this date in Books.
                </span>
              </div>
              <div>
                <label className={LABEL}>Registered books</label>
                <div className="flex flex-wrap gap-x-3 gap-y-1">
                  {(["SJ", "PJ", "CRJ", "CDJ"] as const).map((b) => (
                    <label key={b} className="flex items-center gap-1.5 text-sm text-[var(--text-primary)]">
                      <input
                        type="checkbox"
                        checked={form.books_kept.includes(b)}
                        onChange={(e) =>
                          set("books_kept", e.target.checked ? [...form.books_kept, b] : form.books_kept.filter((x) => x !== b))
                        }
                      />
                      {BOOK_LABELS[b]}
                    </label>
                  ))}
                </div>
                <span className="mt-0.5 block text-[11px] text-[var(--text-secondary)]">
                  General Journal and General Ledger are always kept. Empty = the usual set for the VAT status.
                </span>
              </div>
              <div>
                <label className={LABEL}>Signatory (sworn declaration)</label>
                <input className={INPUT} maxLength={120} value={form.books_signatory} onChange={(e) => set("books_signatory", e.target.value)} />
              </div>
              <div>
                <label className={LABEL}>Signatory title</label>
                <input className={INPUT} maxLength={60} value={form.books_signatory_title} onChange={(e) => set("books_signatory_title", e.target.value)} />
              </div>
            </div>
          </fieldset>
```

Import `BOOK_LABELS` from `@/lib/accounting-format`. If the form's grid isn't two columns at that point, drop `col-span-2`.

- [ ] **Step 5: Document panel** — in `DocumentPanel.tsx`:

1. Imports: add `useCallback` is not needed; add `BOOK_LABELS` is not needed. Add types `Account, PaymentLinks`.
2. Extend `toDraft` with:

```ts
    paid_on: doc.paid_on ?? "",
    paid_via: doc.paid_via,
    payment_ref: doc.payment_ref,
    gl_account_code: doc.gl_account_code,
```

3. In `save`, treat `paid_on` like `doc_date`:

```ts
      if (key === "doc_date" || key === "paid_on") patch[key] = value || null;
```

4. State and loading, after the existing state hooks:

```ts
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [links, setLinks] = useState<PaymentLinks | null>(null);

  useEffect(() => {
    accountingApi.accounts(doc.company_id).then(setAccounts).catch(() => setAccounts([]));
  }, [doc.company_id]);

  useEffect(() => {
    accountingApi.documentPayments(doc.id).then(setLinks).catch(() => setLinks(null));
  }, [doc.id, doc.settles_document_id]);
```

5. Render, right after the `AMOUNTS` grid closes (before the `AssetSection` block):

```tsx
        {["sales", "purchases", "expenses", "payroll"].includes(draft.category) && !doc.settles_document_id && (
          <div className="mt-4 rounded-lg border border-[var(--border)] p-3">
            <p className="mb-2 text-xs font-medium text-[var(--text-secondary)]">Payment (books)</p>
            {links && links.paid_by.length > 0 ? (
              <ul className="space-y-1 text-sm text-[var(--text-primary)]">
                {links.paid_by.map((r) => (
                  <li key={r.id}>Paid by receipt {r.doc_number || "(no number)"} · {r.doc_date ?? "undated"} · {formatPeso(r.gross_amount)}</li>
                ))}
              </ul>
            ) : (
              <div className="grid grid-cols-3 gap-3">
                {field("paid_on", "Paid on", "date")}
                <div>
                  <label className={LABEL}>Paid via</label>
                  <select className={INPUT} value={draft.paid_via} onChange={(e) => setDraft((d) => ({ ...d, paid_via: e.target.value }))}>
                    <option value="">—</option>
                    <option value="cash">Cash</option>
                    <option value="bank">Bank / check</option>
                    <option value="ewallet">E-wallet</option>
                  </select>
                </div>
                {field("payment_ref", "Check / ref no.")}
              </div>
            )}
            {(draft.category === "purchases" || draft.category === "expenses") && accounts.length > 0 && (
              <div className="mt-3">
                <label className={LABEL}>Book to account</label>
                <select className={INPUT} value={draft.gl_account_code} onChange={(e) => setDraft((d) => ({ ...d, gl_account_code: e.target.value }))}>
                  <option value="">Default for “{ACCOUNT_LABELS[draft.account] ?? draft.account}”</option>
                  {accounts.filter((a) => a.active && ["asset", "cost", "expense"].includes(a.type)).map((a) => (
                    <option key={a.id} value={a.code}>{a.code} {a.name}</option>
                  ))}
                </select>
                <span className="mt-0.5 block text-[11px] text-[var(--text-secondary)]">Remembered for this supplier.</span>
              </div>
            )}
          </div>
        )}

        {links && (doc.settles_document_id || links.candidates.length > 0 || doc.doc_type === "receipt") && (
          <div className="mt-4 rounded-lg border border-[var(--border)] p-3">
            <p className="mb-2 text-xs font-medium text-[var(--text-secondary)]">This receipt pays</p>
            <select
              className={INPUT}
              disabled={busy}
              value={doc.settles_document_id ?? ""}
              onChange={(e) => save({ settles_document_id: e.target.value || null })}
            >
              <option value="">Nothing: it is a sale or expense of its own</option>
              {[...(links.linked_invoice ? [links.linked_invoice] : []), ...links.candidates.filter((c) => c.id !== links.linked_invoice?.id)].map((c) => (
                <option key={c.id} value={c.id}>
                  {c.doc_number || "(no number)"} · {c.doc_date ?? "undated"} · {c.counterparty} · {formatPeso(c.gross_amount)}
                </option>
              ))}
            </select>
            <span className="mt-0.5 block text-[11px] text-[var(--text-secondary)]">
              {doc.settles_source === "auto" ? "Linked automatically. " : ""}A linked receipt only records the payment; the invoice is the sale or expense.
            </span>
          </div>
        )}
```

Import `formatPeso` from `@/lib/accounting-format`.

- [ ] **Step 6: Lint and build**

Run: `cd frontend && npm run lint && npm run build`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/types/accounting.ts frontend/src/lib/accounting-api.ts frontend/src/lib/accounting-format.ts frontend/src/components/accounting/CompanyForm.tsx frontend/src/components/accounting/DocumentPanel.tsx
git commit -m "feat(accounting): books settings on companies; payment and receipt links on documents

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: Frontend — Books node, Books panel (opening balances + journal entries), chart editor

**Files:**
- Create: `frontend/src/components/accounting/JournalEntryForm.tsx`
- Create: `frontend/src/components/accounting/ChartEditor.tsx`
- Create: `frontend/src/components/accounting/BooksPanel.tsx`
- Modify: `frontend/src/components/accounting/FolderTree.tsx`
- Modify: `frontend/src/app/accounting/page.tsx`

**Interfaces:**
- Consumes: Task 11 types and API methods.
- Produces: `<BooksPanel companyId year booksStart onChanged />`; `<ChartEditor companyId canManage />`; `<JournalEntryForm accounts initial onCancel onSave />`.

- [ ] **Step 1: Journal entry form**

```tsx
// frontend/src/components/accounting/JournalEntryForm.tsx
"use client";

import { useState } from "react";
import { Plus, Trash } from "@phosphor-icons/react";
import type { Account, JournalEntryInput, JournalLine } from "@/types/accounting";

const INPUT = "w-full px-2 py-1.5 rounded-md border border-[var(--border)] bg-[var(--bg-primary)] text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]";
const BLANK: JournalLine = { account_code: "", debit: "", credit: "", party_name: "", party_tin: "" };

interface Props {
  accounts: Account[];
  initial: JournalEntryInput;
  busy: boolean;
  onCancel: () => void;
  onSave: (entry: JournalEntryInput) => void;
}

const cents = (v: string) => Math.round((Number(v) || 0) * 100);

export default function JournalEntryForm({ accounts, initial, busy, onCancel, onSave }: Props) {
  const [entry, setEntry] = useState<JournalEntryInput>(initial);
  const lines = entry.lines.length >= 2 ? entry.lines : [...entry.lines, BLANK, BLANK].slice(0, 2);
  const debit = lines.reduce((s, l) => s + cents(l.debit), 0);
  const credit = lines.reduce((s, l) => s + cents(l.credit), 0);
  const setLine = (i: number, patch: Partial<JournalLine>) =>
    setEntry((e) => ({ ...e, lines: lines.map((l, j) => (j === i ? { ...l, ...patch } : l)) }));
  const active = accounts.filter((a) => a.active);
  const opening = entry.kind === "opening";

  return (
    <div className="rounded-lg border border-[var(--border)] p-3">
      <div className="mb-3 grid grid-cols-2 gap-3 md:grid-cols-4">
        {!opening && (
          <>
            <input type="date" className={INPUT} value={entry.entry_date} onChange={(e) => setEntry({ ...entry, entry_date: e.target.value })} />
            <select className={INPUT} value={entry.book} onChange={(e) => setEntry({ ...entry, book: e.target.value as JournalEntryInput["book"] })}>
              <option value="GJ">General Journal</option>
              <option value="CRJ">Cash Receipts Journal</option>
              <option value="CDJ">Cash Disbursements Journal</option>
            </select>
          </>
        )}
        <input className={INPUT} placeholder="Reference" maxLength={60} value={entry.reference} onChange={(e) => setEntry({ ...entry, reference: e.target.value })} />
        <input className={INPUT} placeholder="Particulars" maxLength={255} value={entry.particulars} onChange={(e) => setEntry({ ...entry, particulars: e.target.value })} />
      </div>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-[11px] text-[var(--text-secondary)]">
            <th className="pb-1">Account</th><th className="pb-1">Debit</th><th className="pb-1">Credit</th><th className="pb-1">Party (AR/AP)</th><th />
          </tr>
        </thead>
        <tbody>
          {lines.map((l, i) => (
            <tr key={i}>
              <td className="py-0.5 pr-2">
                <select className={INPUT} value={l.account_code} onChange={(e) => setLine(i, { account_code: e.target.value })}>
                  <option value="">Choose…</option>
                  {active.map((a) => (
                    <option key={a.id} value={a.code}>{a.code} {a.name}</option>
                  ))}
                </select>
              </td>
              <td className="py-0.5 pr-2"><input className={INPUT} inputMode="decimal" value={l.debit} onChange={(e) => setLine(i, { debit: e.target.value, credit: e.target.value ? "" : l.credit })} /></td>
              <td className="py-0.5 pr-2"><input className={INPUT} inputMode="decimal" value={l.credit} onChange={(e) => setLine(i, { credit: e.target.value, debit: e.target.value ? "" : l.debit })} /></td>
              <td className="py-0.5 pr-2"><input className={INPUT} maxLength={255} value={l.party_name} onChange={(e) => setLine(i, { party_name: e.target.value })} /></td>
              <td>
                {lines.length > 2 && (
                  <button aria-label="Remove line" className="p-1 text-[var(--text-secondary)]" onClick={() => setEntry({ ...entry, lines: lines.filter((_, j) => j !== i) })}>
                    <Trash size={14} />
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-2 flex flex-wrap items-center gap-3 text-sm">
        <button className="flex items-center gap-1 text-[var(--accent)]" onClick={() => setEntry({ ...entry, lines: [...lines, BLANK] })}>
          <Plus size={13} /> Line
        </button>
        <span className={debit === credit ? "text-[var(--text-secondary)]" : "text-[var(--alert-error-text)]"}>
          Debits ₱{(debit / 100).toLocaleString("en-PH", { minimumFractionDigits: 2 })} · Credits ₱{(credit / 100).toLocaleString("en-PH", { minimumFractionDigits: 2 })}
          {debit !== credit && " — must balance"}
        </span>
        <span className="ml-auto flex gap-2">
          <button className="rounded-lg border border-[var(--border)] px-3 py-1.5" onClick={onCancel}>Cancel</button>
          <button
            className="rounded-lg bg-[var(--accent)] px-3 py-1.5 font-medium text-white disabled:opacity-60"
            disabled={busy || debit !== credit || debit === 0}
            onClick={() =>
              onSave({
                ...entry,
                lines: lines
                  .filter((l) => l.account_code && (l.debit || l.credit))
                  .map((l) => ({ ...l, debit: l.debit || "0", credit: l.credit || "0" })),
              })
            }
          >
            Save
          </button>
        </span>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Chart editor**

```tsx
// frontend/src/components/accounting/ChartEditor.tsx
"use client";

import { useEffect, useState } from "react";
import { Lock } from "@phosphor-icons/react";
import { accountingApi } from "@/lib/accounting-api";
import { apiErrorMessage } from "@/lib/accounting-format";
import type { Account } from "@/types/accounting";

const INPUT = "px-2 py-1 rounded-md border border-[var(--border)] bg-[var(--bg-primary)] text-sm text-[var(--text-primary)]";

export default function ChartEditor({ companyId, canManage }: { companyId: string; canManage: boolean }) {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [error, setError] = useState("");
  const [adding, setAdding] = useState<{ parent: string; code: string; name: string } | null>(null);

  useEffect(() => {
    accountingApi.accounts(companyId).then(setAccounts).catch((e) => setError(apiErrorMessage(e, "Couldn't load the chart")));
  }, [companyId]);

  const replace = (a: Account) => setAccounts((all) => all.map((x) => (x.id === a.id ? a : x)));
  const run = async (fn: () => Promise<void>) => {
    setError("");
    try {
      await fn();
    } catch (e) {
      setError(apiErrorMessage(e, "Couldn't save the account"));
    }
  };

  return (
    <div>
      {error && <p className="mb-2 text-sm text-[var(--alert-error-text)]">{error}</p>}
      <table className="w-full text-sm">
        <tbody>
          {accounts.map((a) => (
            <tr key={a.id} className={`border-b border-[var(--border)] ${a.active ? "" : "opacity-50"}`}>
              <td className="w-20 py-1 font-mono text-xs" style={{ paddingLeft: a.parent_code ? 16 : 0 }}>{a.code}</td>
              <td className="py-1">
                {canManage ? (
                  <input
                    className={`${INPUT} w-full`}
                    defaultValue={a.name}
                    onBlur={(e) => e.target.value.trim() && e.target.value !== a.name && run(async () => replace(await accountingApi.updateAccount(a.id, { name: e.target.value })))}
                  />
                ) : (
                  a.name
                )}
              </td>
              <td className="w-24 py-1 text-xs text-[var(--text-secondary)]">{a.type}{a.contra ? " (contra)" : ""}</td>
              <td className="w-40 py-1 text-right text-xs">
                {a.system_key ? (
                  <span className="inline-flex items-center gap-1 text-[var(--text-secondary)]"><Lock size={12} /> used by posting</span>
                ) : canManage ? (
                  <button className="text-[var(--accent)]" onClick={() => run(async () => replace(await accountingApi.updateAccount(a.id, { active: !a.active })))}>
                    {a.active ? "Deactivate" : "Activate"}
                  </button>
                ) : null}
                {canManage && a.active && (
                  <button className="ml-3 text-[var(--accent)]" onClick={() => setAdding({ parent: a.code, code: "", name: "" })}>Sub-account</button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {adding && (
        <div className="mt-3 flex flex-wrap items-center gap-2 text-sm">
          <span className="text-[var(--text-secondary)]">Under {adding.parent}:</span>
          <input className={`${INPUT} w-24`} placeholder="Code" value={adding.code} onChange={(e) => setAdding({ ...adding, code: e.target.value.replace(/\D/g, "") })} />
          <input className={`${INPUT} w-64`} placeholder="Name" value={adding.name} onChange={(e) => setAdding({ ...adding, name: e.target.value })} />
          <button
            className="rounded-lg bg-[var(--accent)] px-3 py-1 font-medium text-white disabled:opacity-60"
            disabled={adding.code.length < 4 || !adding.name.trim()}
            onClick={() =>
              run(async () => {
                const created = await accountingApi.addAccount(companyId, { code: adding.code, name: adding.name, parent_code: adding.parent });
                setAccounts((all) => [...all, created].sort((x, y) => x.code.localeCompare(y.code)));
                setAdding(null);
              })
            }
          >
            Add
          </button>
          <button onClick={() => setAdding(null)}>Cancel</button>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Books panel**

```tsx
// frontend/src/components/accounting/BooksPanel.tsx
"use client";

import { useCallback, useEffect, useState } from "react";
import { accountingApi } from "@/lib/accounting-api";
import { apiErrorMessage, formatPeso } from "@/lib/accounting-format";
import ChartEditor from "@/components/accounting/ChartEditor";
import JournalEntryForm from "@/components/accounting/JournalEntryForm";
import type { Account, JournalEntry, JournalEntryInput } from "@/types/accounting";

interface Props {
  companyId: string;
  year: number;
  booksStart: string;
  canManage: boolean;
  onChanged: () => void;
}

const BTN = "rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)]";

export default function BooksPanel({ companyId, year, booksStart, canManage, onChanged }: Props) {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [entries, setEntries] = useState<JournalEntry[]>([]);
  const [editing, setEditing] = useState<{ id?: string; input: JournalEntryInput } | null>(null);
  const [showChart, setShowChart] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    const [a, e] = await Promise.all([accountingApi.accounts(companyId), accountingApi.journalEntries(companyId, year)]);
    setAccounts(a);
    setEntries(e);
  }, [companyId, year]);

  useEffect(() => {
    load().catch((e) => setError(apiErrorMessage(e, "Couldn't load the books")));
  }, [load]);

  const opening = entries.find((e) => e.kind === "opening");
  const blank = (kind: "opening" | "manual"): JournalEntryInput => ({
    kind, book: "GJ", entry_date: kind === "opening" ? booksStart : booksStart, reference: kind === "opening" ? "OB" : "",
    particulars: kind === "opening" ? "Opening balances" : "", lines: [],
  });
  const title = (code: string) => accounts.find((a) => a.code === code)?.name ?? code;
  // Stored lines carry "0" on the empty side; the form wants it blank.
  const editable = (e: JournalEntry): JournalEntryInput => ({
    ...e,
    lines: e.lines.map((l) => ({ ...l, debit: Number(l.debit) ? l.debit : "", credit: Number(l.credit) ? l.credit : "" })),
  });

  async function save(input: JournalEntryInput) {
    setBusy(true);
    setError("");
    try {
      if (editing?.id) await accountingApi.updateJournalEntry(editing.id, input);
      else await accountingApi.createJournalEntry(companyId, input);
      setEditing(null);
      await load();
      onChanged();
    } catch (e) {
      setError(apiErrorMessage(e, "Couldn't save the entry"));
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: string) {
    setBusy(true);
    try {
      await accountingApi.deleteJournalEntry(id);
      await load();
      onChanged();
    } catch (e) {
      setError(apiErrorMessage(e, "Couldn't delete the entry"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mb-6">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <h2 className="text-base font-semibold text-[var(--text-primary)]">Books · FY {year}</h2>
        <span className="text-xs text-[var(--text-secondary)]">Books start {booksStart}. Journals, ledger and trial balance are in each quarter&apos;s workbook.</span>
        <button className={`${BTN} ml-auto`} onClick={() => setShowChart((s) => !s)}>{showChart ? "Hide" : "Chart of accounts"}</button>
      </div>
      {error && <p className="mb-2 text-sm text-[var(--alert-error-text)]">{error}</p>}
      {showChart && (
        <div className="mb-4 rounded-lg border border-[var(--border)] p-3">
          <ChartEditor companyId={companyId} canManage={canManage} />
        </div>
      )}

      <section className="mb-4">
        <div className="mb-2 flex items-center gap-2">
          <h3 className="text-sm font-semibold text-[var(--text-primary)]">Opening balances</h3>
          {!editing && (
            <button className={BTN} onClick={() => setEditing(opening ? { id: opening.id, input: editable(opening) } : { input: blank("opening") })}>
              {opening ? "Edit" : "Enter opening balances"}
            </button>
          )}
        </div>
        {opening && editing?.id !== opening.id && (
          <p className="text-xs text-[var(--text-secondary)]">
            {opening.lines.length} accounts as of {opening.entry_date} · total {formatPeso(opening.lines.reduce((s, l) => s + Number(l.debit), 0))}
          </p>
        )}
      </section>

      <section>
        <div className="mb-2 flex items-center gap-2">
          <h3 className="text-sm font-semibold text-[var(--text-primary)]">Journal entries</h3>
          {!editing && <button className={BTN} onClick={() => setEditing({ input: blank("manual") })}>New entry</button>}
        </div>
        {editing && (
          <JournalEntryForm accounts={accounts} initial={editing.input} busy={busy} onCancel={() => setEditing(null)} onSave={save} />
        )}
        <ul className="mt-2 divide-y divide-[var(--border)]">
          {entries.filter((e) => e.kind === "manual").map((e) => (
            <li key={e.id} className="flex flex-wrap items-baseline gap-3 py-2 text-sm">
              <span className="w-24 text-[var(--text-secondary)]">{e.entry_date}</span>
              <span className="w-10 text-xs text-[var(--text-secondary)]">{e.book}</span>
              <span className="flex-1 text-[var(--text-primary)]">
                {e.particulars || e.reference || "(no particulars)"} ·{" "}
                {e.lines.map((l) => `${title(l.account_code)} ${Number(l.debit) ? "Dr" : "Cr"} ${formatPeso(Number(l.debit) || Number(l.credit))}`).join(" / ")}
              </span>
              <button className="text-[var(--accent)]" onClick={() => setEditing({ id: e.id, input: editable(e) })}>Edit</button>
              <button className="text-[var(--alert-error-text)]" disabled={busy} onClick={() => remove(e.id)}>Delete</button>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
```

- [ ] **Step 4: Tree node** — in `FolderTree.tsx`, change `isSelected` to compare the view too:

```ts
  const isSelected = (ref: FolderRef) =>
    selected?.companyId === ref.companyId && selected.year === ref.year && selected.quarter === ref.quarter &&
    (selected.view ?? null) === (ref.view ?? null);
```

and inside each year's `<ul>`, as the first item:

```tsx
                {c.books_start && (
                  <li>{leaf({ companyId: c.id, year: y.year, quarter: null, view: "books" }, "Books", null, 0)}</li>
                )}
```

- [ ] **Step 5: Page wiring** — in `app/accounting/page.tsx`:

1. Import `BooksPanel`.
2. In `loadFolder`, skip the books view:

```ts
    setFolder(ref && ref.quarter !== 0 && ref.view !== "books" ? await accountingApi.folder(ref.companyId, ref.year, ref.quarter) : null);
```

3. Next to the `AnnualPanel` block, render:

```tsx
            {selected?.view === "books" && selected.year !== null && (() => {
              const company = tree.find((c) => c.id === selected.companyId);
              return company?.books_start ? (
                <BooksPanel
                  companyId={selected.companyId}
                  year={selected.year}
                  booksStart={company.books_start}
                  canManage={canManage}
                  onChanged={() => loadTree().catch(() => undefined)}
                />
              ) : null;
            })()}
```

4. In the empty-state ternary (`folder ? <FileGrid …/> : selected?.quarter === 0 ? null : <p>…`), also return `null` when `selected?.view === "books"`.

- [ ] **Step 6: Lint and build**

Run: `cd frontend && npm run lint && npm run build`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/accounting/JournalEntryForm.tsx frontend/src/components/accounting/ChartEditor.tsx frontend/src/components/accounting/BooksPanel.tsx frontend/src/components/accounting/FolderTree.tsx frontend/src/app/accounting/page.tsx
git commit -m "feat(accounting): Books node with opening balances, journal entries and chart of accounts

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 13: End-to-end check in the running app

**Files:** none new (fixes only, each with its own test + commit).

- [ ] **Step 1: Full backend suite**

Run: `docker compose exec -T backend python -m pytest -q`
Expected: all pass. Also `docker compose exec -T backend ruff check app` (install with `docker compose exec -T backend pip install ruff` if missing) — no new errors in the files this plan touched.

- [ ] **Step 2: Rebuild the frontend container** (it's a prebuilt image)

Run: `docker compose up --build -d frontend backend`

- [ ] **Step 3: Walk through the flow** (local test company, e.g. "ZZ E2E Textile Trading Corp", TIN 555-666-777, already in the local DB)

1. Companies → edit → set **Books start** to the first day of the current fiscal quarter; save. Tree shows **Books** under the year.
2. Books → **Enter opening balances**: Cash on hand 50,000 Dr / Share capital 50,000 Cr → save. Chart of accounts: add sub-account 6021 "Rent - warehouse" under 6020.
3. Open a sales invoice in the quarter → Payment: paid on (a date in the quarter), via Bank → save. Open a supplier invoice → Book to account 6021 → save.
4. If the folder has an official/collection receipt for an invoice: confirm "This receipt pays" shows the invoice (auto-linked) and that the quarter's returns no longer count it twice (compare 2550-Q 31A / Expenses before and after).
5. Generate the quarter. In the output viewer the ledger list shows SJ, PJ, CRJ, CDJ, GJ, GL, AR, AP, TB. Download the workbook: TB total debits = credits; SJ total AR = SLS gross sales; PJ input VAT = SLP input tax; CRJ shows the bank collection.
6. Prepare returns → mark 0619-E M1 filed → the quarter shows **Stale**; regenerate → CDJ has the BIR payment.
7. Clear Books start on the company → regenerate → no book tabs; tree hides **Books**.

- [ ] **Step 4: Record and commit any fixes** (each fix: failing test → fix → passing test → commit `fix(accounting): …`).
