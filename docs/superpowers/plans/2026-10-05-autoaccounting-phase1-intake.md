# AutoAccounting Phase 1 (Intake) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A firm can drop a client's receipts and invoices onto a Drive-style page, confirm (or create) the client company, and see every document extracted, classified and filed under Company → Year → Quarter → category, with a review queue for anything doubtful.

**Architecture:** A new self-contained module beside the 2307 pipeline. Pure logic (fiscal periods, company matching, Gemini-JSON parsing, classification, tree assembly) lives in `app/services/accounting/*.py` and is unit-tested. A background pipeline (`pipeline.py`) runs a cheap first-page detection pass, then — after the user confirms the company — a full extraction pass that writes one `aa_documents` row per logical document. A new router `/api/accounting` and a new page `/accounting` sit on top, behind a new `accounting` feature toggle that ships **off**.

**Tech Stack:** FastAPI + async SQLAlchemy + Pydantic v2, Gemini via the existing `gemini_service`, PyMuPDF, pytest (in the backend container); Next.js 15 + React 19 + Tailwind 4, `react-dropzone`, `@phosphor-icons/react`.

**Spec:** AutoAccounting spec sheet (Claude Doc): https://claude.ai/code/artifact/8dcfb05b-3f3e-4410-a082-da75a391cd21 — Phase 1 = sections *Company databank*, *Drive-style browser and auto-sorter*, *Document extraction and classification* (+ the Phase 1 band of *Rollout*).

## Global Constraints

- Every table is scoped by `enterprise_id` (the firm-owner user id); every query filters on it. Admin acts as its own enterprise.
- Amounts are stored as `NUMERIC(14,2)` and handled as `Decimal` — never float, never string.
- Gemini only extracts; no tax figure is computed by the model.
- Additive schema goes through `Base.metadata.create_all` + `startup_migrations._run_migrations` (indexes); nothing destructive.
- No session state across transactions (Supabase transaction pooler): no advisory locks, temp tables, LISTEN. Do not hold a DB transaction open across a Gemini call (commit before calling out).
- Source documents must be kept ≥ 5 years: they go under `settings.accounting_root`, never the 1-day OCR bucket in production.
- Feature key is `accounting`; it ships disabled (`feature_toggles` row `enabled=false`) until the owner turns it on.
- Accepted uploads in Phase 1: PDF, PNG, JPG/JPEG. Spreadsheets/HEIC are Phase 2.
- Billing: extraction pages are charged through `usage_service.charge_for_pages` + `increment_usage`, once per file (`pages_charged`). Detection is not billed.
- Only `admin` / `enterprise` / `manager` may create or edit companies; employees may upload and confirm existing companies.
- Backend tests: `docker compose exec -T backend python -m pytest -q` (no local pip). Frontend: `npm run lint` and `npm run build` in `frontend/` on the host.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Work on the current branch `AutoAccounting`; do not push.

## Review Focus

1. **Empty or corrupt file** (0 bytes, a `.pdf` PyMuPDF can't open) → rejected at upload with a message naming the file; never a stuck "detecting" job. Pinned in Task 6 (`test_stream_upload_rejects_empty`, `test_stream_upload_rejects_unreadable_pdf`).
2. **The same receipt dropped twice** (same file, or the same invoice scanned again) → the second copy is marked duplicate/"possible duplicate", not silently double-counted or double-billed. Pinned in Task 4 (`test_mark_duplicate_flags_second_copy`); file-hash dedupe is verified manually in Task 12.
3. **Gemini returns junk** (fenced JSON, prose, empty list) → the file still yields one *Unsorted* document flagged `nothing_extracted`, so nothing vanishes. Pinned in Task 3 (`test_parse_extraction_garbage_returns_empty`) and Task 4 (`test_empty_document_fields`).
4. **Documents dated outside the quarter being worked on, or companies with a non-December fiscal year** → filed in their own fiscal period. Pinned in Task 2 and Task 4 (`test_period_follows_document_date_and_fiscal_year`).
5. **Double-clicking "Confirm"** → extraction runs once. Enforced by a conditional `UPDATE … WHERE status='awaiting_confirmation'` in Task 8; verified manually in Task 12.

## Deviations from the spec (Phase 1 scope decisions)

- The spec's `aa_transactions` is folded into `aa_documents` (one logical document = one row with its amounts). The physical upload is `aa_files`. Excel line items arrive in Phase 2 as a child table.
- Documents with no readable date live in a company-level **Undated** folder (no quarter can be inferred).
- Moving a document between categories/quarters is done from the document panel (selects), not drag-and-drop; drag-to-move is a later polish.
- Search filters the company tree by name/TIN only. Search by supplier name / invoice number comes with Phase 2.
- No `aa_periods`, `aa_outputs`, `aa_carryovers` yet (Phase 2). Quarter status chips (*Generated*, *Stale*, *Filed*) and the "DRAFT — n unreviewed" watermark arrive with outputs in Phase 2; Phase 1 shows the open-review count.
- Employees cannot add companies in Phase 1 (the "Add to databank" button is disabled with a hint). The per-firm "employees may add companies" toggle is Phase 2.
- No right-click menu: open / move / exclude / delete live in the document panel.
- Payroll registers and 2307s are classified and filed but only totals are extracted; per-employee compensation lines (1601-C) and the expected-EWT ATC per payment are Phase 3.
- Classify-time check order note: `test_accounting_classify.py` is written in Task 4 but needs `app.models.accounting` (Task 5), so it is run in Task 5.

## File Structure

**Backend — create**
- `backend/app/services/accounting/__init__.py` — package marker.
- `backend/app/services/accounting/periods.py` — fiscal year/quarter arithmetic (pure).
- `backend/app/services/accounting/parsing.py` — TIN, money, date normalisers (pure).
- `backend/app/services/accounting/extraction.py` — Gemini prompts + JSON → dataclasses (pure).
- `backend/app/services/accounting/matching.py` — company matching, upload grouping, detection JSON (pure).
- `backend/app/services/accounting/classify.py` — extracted doc → `aa_documents` field dict (pure).
- `backend/app/services/accounting/tree.py` — folder tree + folder counts (pure).
- `backend/app/services/accounting/storage.py` — stream uploads to the accounting root.
- `backend/app/services/accounting/pipeline.py` — background detection + extraction (DB + Gemini).
- `backend/app/models/accounting.py` — `AACompany`, `AAUpload`, `AAFile`, `AADocument`, `AASupplierRule`.
- `backend/app/schemas/accounting.py` — request/response models.
- `backend/app/routers/accounting.py` — `/api/accounting/*`.
- Tests: `backend/tests/test_accounting_periods.py`, `test_accounting_parsing.py`, `test_accounting_extraction.py`, `test_accounting_matching.py`, `test_accounting_classify.py`, `test_accounting_tree.py`, `test_accounting_storage.py`, `test_accounting_schemas.py`.

**Backend — modify**
- `backend/app/config.py` — `accounting_dir` + `accounting_root`.
- `backend/app/services/file_service.py:75-90` — accept the accounting root in `validate_stored_path`.
- `backend/app/services/gemini_service.py` — public `call_gemini_raw`, `pdf_chunks_for_gemini`.
- `backend/app/models/feature_toggle.py:23-34` — add `"accounting"`.
- `backend/app/startup_migrations.py` — indexes + toggle row (end of `_run_migrations`).
- `backend/app/main.py` — import model, mount router.
- `backend/tests/test_feature_toggle_keys.py` — key test.

**Frontend — create**
- `frontend/src/types/accounting.ts` — API types.
- `frontend/src/lib/accounting-format.ts` — labels + formatters.
- `frontend/src/components/accounting/CompanyForm.tsx` — add/edit company modal.
- `frontend/src/components/accounting/CompanyPicker.tsx` — "Drop files for:" select.
- `frontend/src/components/accounting/FolderTree.tsx` — left tree.
- `frontend/src/components/accounting/FileGrid.tsx` — category tiles + document table.
- `frontend/src/components/accounting/DocumentPanel.tsx` — document viewer/editor slide-over.
- `frontend/src/components/accounting/UploadReviewDialog.tsx` — company confirmation dialog.
- `frontend/src/app/accounting/page.tsx` — the page.

**Frontend — modify**
- `frontend/src/lib/api.ts` — `accountingApi`.
- `frontend/src/types/index.ts:406-416` — `FeatureToggleKey` += `"accounting"`.
- `frontend/src/app/providers.tsx:47-108` — route access + feature path.
- `frontend/src/components/layout/Sidebar.tsx:44-59` — nav item.
- `frontend/src/components/enterprise/feature-meta.ts`, `frontend/src/components/owner/feature-tabs.ts` — key metadata.

---

### Task 1: Backend plumbing — storage root, Gemini entry points, feature key

**Files:**
- Modify: `backend/app/config.py` (after the `assets_root` property, ~line 67)
- Modify: `backend/app/services/file_service.py:75-90`
- Modify: `backend/app/services/gemini_service.py` (append after `detect_form`, ~line 305)
- Modify: `backend/app/models/feature_toggle.py:23-34`
- Test: `backend/tests/test_feature_toggle_keys.py`

**Interfaces:**
- Produces: `settings.accounting_dir: str`, `settings.accounting_root -> str`; `gemini_service.call_gemini_raw(file_bytes: bytes, mime_type: str, prompt: str, user_id: str) -> str` (async); `gemini_service.pdf_chunks_for_gemini(pdf_path: str) -> list[tuple[bytes, int, int]]` (bytes, start page 0-based, end page 0-based inclusive); `"accounting" in TOGGLEABLE_KEYS`.

- [ ] **Step 1: Write the failing test** — append to `backend/tests/test_feature_toggle_keys.py`:

```python
def test_accounting_is_a_toggleable_key():
    assert "accounting" in TOGGLEABLE_KEYS


def test_accounting_root_falls_back_to_upload_dir():
    from app.config import Settings

    s = Settings(upload_dir="/tmp/up", accounting_dir="")
    assert s.accounting_root == "/tmp/up"
    s2 = Settings(upload_dir="/tmp/up", accounting_dir="/mnt/acct")
    assert s2.accounting_root == "/mnt/acct"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec -T backend python -m pytest tests/test_feature_toggle_keys.py -v`
Expected: FAIL (`'accounting' not in TOGGLEABLE_KEYS`, `unexpected keyword argument 'accounting_dir'` / no attribute `accounting_root`).

- [ ] **Step 3: Implement**

`backend/app/models/feature_toggle.py` — add the key at the end of the tuple:

```python
    "invoices",
    "accounting",
)
```

`backend/app/config.py` — add the field next to `assets_dir` and the property next to `assets_root`:

```python
    # AutoAccounting source documents. Tax records must be kept ≥5 years, so in
    # production this is a dedicated GCS bucket mounted here (never the 1-day
    # OCR bucket). Unset in dev → falls back to upload_dir.
    accounting_dir: str = ""
```

```python
    @property
    def accounting_root(self) -> str:
        """Filesystem root for AutoAccounting documents (long retention).
        Falls back to upload_dir so dev keeps a single local tree."""
        return self.accounting_dir or self.upload_dir
```

`backend/app/services/file_service.py` — in `validate_stored_path`, replace the `roots = …` line:

```python
    roots = {
        Path(settings.upload_dir).resolve(),
        Path(settings.assets_root).resolve(),
        Path(settings.accounting_root).resolve(),
    }
```

`backend/app/services/gemini_service.py` — append after `detect_form` (before `MIME_MAP`):

```python
async def call_gemini_raw(file_bytes: bytes, mime_type: str, prompt: str, user_id: str) -> str:
    """One Gemini call with a caller-supplied prompt (used by AutoAccounting).

    Shares the per-user/global rate limiters, prompt cache and transient retry
    of ``_call_gemini``. Returns the raw response text.
    """
    return await _call_gemini(_get_gemini_client(), file_bytes, mime_type, prompt, user_id)


def pdf_chunks_for_gemini(pdf_path: str) -> list[tuple[bytes, int, int]]:
    """Compress a PDF and split it into ≤32 MB chunks.

    Returns ``(chunk_bytes, start_page_0indexed, end_page_0indexed_inclusive)``.
    """
    page_count = get_pdf_page_count(pdf_path)
    return _split_pdf_into_chunks(_compress_pdf(pdf_path), page_count)
```

(`get_pdf_page_count`, `_split_pdf_into_chunks`, `_compress_pdf` are module-level functions defined later in the file; they resolve at call time.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec -T backend python -m pytest tests/test_feature_toggle_keys.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/config.py backend/app/services/file_service.py backend/app/services/gemini_service.py backend/app/models/feature_toggle.py backend/tests/test_feature_toggle_keys.py
git commit -m "feat(accounting): storage root, Gemini entry points, feature key

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Fiscal periods

**Files:**
- Create: `backend/app/services/accounting/__init__.py`, `backend/app/services/accounting/periods.py`
- Test: `backend/tests/test_accounting_periods.py`

**Interfaces:**
- Produces: `Period(fiscal_year: int, quarter: int, month_in_quarter: int)` (frozen dataclass); `period_for(d: date, fiscal_year_end_month: int = 12) -> Period`; `quarter_label(quarter: int, fiscal_year_end_month: int = 12) -> str` e.g. `"Q3 (Jul–Sep)"`. Fiscal year is named by the calendar year it **ends** in.

- [ ] **Step 1: Write the failing test** — `backend/tests/test_accounting_periods.py`:

```python
from datetime import date

import pytest

from app.services.accounting.periods import Period, period_for, quarter_label


def test_calendar_year_quarters():
    assert period_for(date(2026, 1, 5)) == Period(2026, 1, 1)
    assert period_for(date(2026, 3, 31)) == Period(2026, 1, 3)
    assert period_for(date(2026, 8, 14)) == Period(2026, 3, 2)
    assert period_for(date(2026, 12, 31)) == Period(2026, 4, 3)


def test_june_fiscal_year_end():
    assert period_for(date(2026, 7, 1), 6) == Period(2027, 1, 1)
    assert period_for(date(2026, 12, 15), 6) == Period(2027, 2, 3)
    assert period_for(date(2027, 6, 30), 6) == Period(2027, 4, 3)


def test_quarter_labels():
    assert quarter_label(3) == "Q3 (Jul–Sep)"
    assert quarter_label(1, 6) == "Q1 (Jul–Sep)"
    assert quarter_label(4, 6) == "Q4 (Apr–Jun)"


def test_rejects_bad_inputs():
    with pytest.raises(ValueError):
        period_for(date(2026, 1, 1), 13)
    with pytest.raises(ValueError):
        quarter_label(5)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec -T backend python -m pytest tests/test_accounting_periods.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.accounting'`.

- [ ] **Step 3: Implement**

`backend/app/services/accounting/__init__.py`:

```python
"""AutoAccounting: document intake, classification and BIR form preparation."""
```

`backend/app/services/accounting/periods.py`:

```python
"""Fiscal period arithmetic for AutoAccounting (pure)."""

from dataclasses import dataclass
from datetime import date

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


@dataclass(frozen=True)
class Period:
    fiscal_year: int       # the calendar year the fiscal year ends in
    quarter: int           # 1..4
    month_in_quarter: int  # 1..3


def _check_fye(fiscal_year_end_month: int) -> None:
    if not 1 <= fiscal_year_end_month <= 12:
        raise ValueError("fiscal_year_end_month must be between 1 and 12")


def period_for(d: date, fiscal_year_end_month: int = 12) -> Period:
    """The fiscal period a document dated ``d`` belongs to."""
    _check_fye(fiscal_year_end_month)
    start_month = fiscal_year_end_month % 12 + 1
    offset = (d.month - start_month) % 12
    fiscal_year = d.year if d.month <= fiscal_year_end_month else d.year + 1
    return Period(fiscal_year, offset // 3 + 1, offset % 3 + 1)


def quarter_label(quarter: int, fiscal_year_end_month: int = 12) -> str:
    """Human label with the quarter's calendar months, e.g. ``Q3 (Jul–Sep)``."""
    _check_fye(fiscal_year_end_month)
    if not 1 <= quarter <= 4:
        raise ValueError("quarter must be between 1 and 4")
    first = (fiscal_year_end_month + (quarter - 1) * 3) % 12
    last = (first + 2) % 12
    return f"Q{quarter} ({_MONTHS[first]}–{_MONTHS[last]})"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec -T backend python -m pytest tests/test_accounting_periods.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/accounting/__init__.py backend/app/services/accounting/periods.py backend/tests/test_accounting_periods.py
git commit -m "feat(accounting): fiscal period arithmetic

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Value parsing + Gemini prompts and response parsing

**Files:**
- Create: `backend/app/services/accounting/parsing.py`, `backend/app/services/accounting/extraction.py`
- Test: `backend/tests/test_accounting_parsing.py`, `backend/tests/test_accounting_extraction.py`

**Interfaces:**
- Consumes: `app.ocr.clean_amount`, `app.ocr.clean_text`.
- Produces:
  - `parsing.normalize_tin(text: str | None) -> tuple[str, str]` → `(9-digit base, 5-digit branch)`, `("", "")` if < 9 digits.
  - `parsing.parse_money(value) -> Decimal` (2 dp, `Decimal("0.00")` on junk; `(500)` → `-500.00`).
  - `parsing.parse_doc_date(value) -> date | None` (ISO, `MM/DD/YYYY`, `MM-DD-YYYY`, `Month D, YYYY`; years 2000–2100 only).
  - `extraction.Party(name="", tin="", branch="00000", address="")` frozen dataclass.
  - `extraction.Detection(document_title: str, kind: str, seller: Party, buyer: Party, doc_date: date | None)`.
  - `extraction.ExtractedDoc` dataclass (fields below).
  - `extraction.KINDS`, `extraction.NATURES`, `extraction.EXPENSE_ACCOUNTS` (tuples).
  - `extraction.DETECT_PROMPT`, `extraction.EXTRACT_PROMPT` (str).
  - `extraction.parse_detection(raw: str) -> Detection`.
  - `extraction.parse_extraction(raw: str, page_offset: int = 0, chunk_pages: int | None = None) -> list[ExtractedDoc]` — pages in the result are **1-based, file-global** (`page_offset` is the chunk's 0-based start page).

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_accounting_parsing.py`:

```python
from datetime import date
from decimal import Decimal

from app.services.accounting.parsing import normalize_tin, parse_doc_date, parse_money


def test_normalize_tin_splits_base_and_branch():
    assert normalize_tin("123-456-789-000") == ("123456789", "00000")
    assert normalize_tin("VAT REG TIN: 123 456 789 00001") == ("123456789", "00001")
    assert normalize_tin("123456789") == ("123456789", "00000")


def test_normalize_tin_rejects_short_or_empty():
    assert normalize_tin("12345") == ("", "")
    assert normalize_tin(None) == ("", "")
    assert normalize_tin("") == ("", "")


def test_parse_money_handles_text_numbers_and_junk():
    assert parse_money("₱1,234.50") == Decimal("1234.50")
    assert parse_money(1234.5) == Decimal("1234.50")
    assert parse_money("(500.00)") == Decimal("-500.00")
    assert parse_money("") == Decimal("0.00")
    assert parse_money(None) == Decimal("0.00")
    assert parse_money("n/a") == Decimal("0.00")
    assert parse_money(float("nan")) == Decimal("0.00")
    assert parse_money(True) == Decimal("0.00")


def test_parse_doc_date_formats():
    assert parse_doc_date("2026-08-14") == date(2026, 8, 14)
    assert parse_doc_date("08/14/2026") == date(2026, 8, 14)
    assert parse_doc_date("August 14, 2026") == date(2026, 8, 14)
    assert parse_doc_date("Aug 14, 2026") == date(2026, 8, 14)


def test_parse_doc_date_rejects_garbage_and_out_of_range():
    assert parse_doc_date("") is None
    assert parse_doc_date(None) is None
    assert parse_doc_date("yesterday") is None
    assert parse_doc_date("1899-01-01") is None
```

`backend/tests/test_accounting_extraction.py`:

```python
from datetime import date
from decimal import Decimal

from app.services.accounting.extraction import Party, parse_detection, parse_extraction


def test_parse_detection_reads_parties():
    raw = (
        '```json\n{"document_title": "SALES INVOICE", "kind": "invoice",'
        ' "seller": {"name": "Cebu Fabric Supply", "tin": "111-222-333-000"},'
        ' "buyer": {"name": "Juan\'s Cloth Trading", "tin": "123-456-789-00000"},'
        ' "date": "2026-08-14"}\n```'
    )
    det = parse_detection(raw)
    assert det.kind == "invoice"
    assert det.seller == Party(name="Cebu Fabric Supply", tin="111222333", branch="00000")
    assert det.buyer.tin == "123456789"
    assert det.doc_date == date(2026, 8, 14)


def test_parse_detection_garbage_is_empty():
    det = parse_detection("I could not read this page.")
    assert det.kind == "other"
    assert det.seller == Party() and det.buyer == Party()
    assert det.doc_date is None


def test_parse_extraction_multiple_documents_with_page_offset():
    raw = """{"documents": [
      {"page_start": 1, "page_end": 1, "document_title": "OFFICIAL RECEIPT", "kind": "receipt",
       "doc_number": "0042", "date": "2026-07-03",
       "seller": {"name": "Max's Restaurant", "tin": "222-333-444-000", "address": "Makati", "vat_registered": true},
       "buyer": {"name": "", "tin": "", "address": ""},
       "gross_amount": 1120, "vatable_amount": 1000, "vat_amount": 120, "exempt_amount": 0,
       "zero_rated_amount": 0, "withholding_amount": 0, "nature": "services",
       "expense_account": "representation", "confidence": 88},
      {"page_start": 2, "page_end": 3, "document_title": "SALES INVOICE", "kind": "invoice",
       "doc_number": "SI-7", "date": "2026-07-09", "seller": {"name": "A"}, "buyer": {"name": "B"},
       "gross_amount": "5,600.00", "nature": "goods_for_resale", "expense_account": "nonsense",
       "confidence": 120}
    ]}"""
    docs = parse_extraction(raw, page_offset=10, chunk_pages=3)
    assert [(d.page_start, d.page_end) for d in docs] == [(11, 11), (12, 13)]
    first, second = docs
    assert first.seller_vat_registered is True
    assert first.vat_amount == Decimal("120.00")
    assert first.expense_account == "representation"
    assert second.gross_amount == Decimal("5600.00")
    assert second.expense_account == "other"
    assert second.confidence == 100.0
    assert second.seller_vat_registered is None


def test_parse_extraction_clamps_pages_to_chunk():
    raw = '{"documents": [{"page_start": 7, "page_end": 2, "kind": "receipt"}]}'
    [doc] = parse_extraction(raw, page_offset=0, chunk_pages=3)
    assert (doc.page_start, doc.page_end) == (3, 3)


def test_parse_extraction_garbage_returns_empty():
    assert parse_extraction("Sorry, nothing here") == []
    assert parse_extraction('{"documents": "none"}') == []
    assert parse_extraction("") == []


def test_parse_extraction_unknown_kind_and_nature_become_other():
    [doc] = parse_extraction('[{"kind": "spaceship", "nature": "magic"}]')
    assert doc.kind == "other"
    assert doc.nature == "other"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec -T backend python -m pytest tests/test_accounting_parsing.py tests/test_accounting_extraction.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`backend/app/services/accounting/parsing.py`:

```python
"""Value normalisers for AutoAccounting extraction output (pure)."""

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from app.ocr import clean_amount

_CENT = Decimal("0.01")
_ZERO = Decimal("0.00")
_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%B %d, %Y", "%b %d, %Y")


def normalize_tin(text: str | None) -> tuple[str, str]:
    """Split a printed TIN into (9-digit base, 5-digit branch code).

    Returns ("", "") when fewer than 9 digits are present. Old 3-digit branch
    codes ("000") are zero-padded to the current 5-digit form.
    """
    digits = re.sub(r"\D", "", text or "")
    if len(digits) < 9:
        return "", ""
    branch = digits[9:14].zfill(5) if len(digits) > 9 else "00000"
    return digits[:9], branch


def parse_money(value) -> Decimal:
    """Parse an amount from Gemini JSON (number or text) into a 2-dp Decimal."""
    if value is None or isinstance(value, bool):
        return _ZERO
    try:
        if isinstance(value, (int, float, Decimal)):
            return Decimal(str(value)).quantize(_CENT)
        text = str(value)
        negative = "(" in text and ")" in text
        cleaned = clean_amount(text).replace(",", "")
        amount = Decimal(cleaned).quantize(_CENT)
        return -abs(amount) if negative else amount
    except (InvalidOperation, ValueError):
        return _ZERO


def parse_doc_date(value) -> date | None:
    """Parse a document date; None if unreadable or outside 2000–2100."""
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    for fmt in _DATE_FORMATS:
        try:
            parsed = datetime.strptime(text, fmt).date()
        except ValueError:
            continue
        return parsed if 2000 <= parsed.year <= 2100 else None
    return None
```

`backend/app/services/accounting/extraction.py`:

```python
"""Gemini prompts for AutoAccounting and parsing of their JSON replies (pure)."""

import json
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.ocr import clean_text
from app.services.accounting.parsing import normalize_tin, parse_doc_date, parse_money

KINDS = ("invoice", "receipt", "bir2307", "payroll", "import", "statement", "other")
NATURES = ("goods_for_resale", "raw_materials", "capital_goods", "services", "import", "payroll", "other")
EXPENSE_ACCOUNTS = (
    "purchases", "raw_materials", "importation", "capital_goods", "salaries", "rent",
    "utilities", "professional_fees", "office_supplies", "representation",
    "transportation", "repairs", "taxes_licenses", "other",
)

DETECT_PROMPT = """You are reading a Philippine business document (receipt, invoice, BIR form, payroll sheet, import papers).
Look at this first page and identify the two parties.

Reply with ONLY valid JSON, no markdown fences, no explanation:
{"document_title": "<title printed on the document, e.g. SALES INVOICE, OFFICIAL RECEIPT, BIR FORM 2307>",
 "kind": "<invoice|receipt|bir2307|payroll|import|statement|other>",
 "seller": {"name": "<issuer / seller / payee>", "tin": "<TIN as printed>"},
 "buyer": {"name": "<customer / buyer / payor>", "tin": "<TIN as printed>"},
 "date": "<document date as YYYY-MM-DD, or empty>"}

Rules:
- On a BIR Form 2307 the payee is the seller and the payor is the buyer.
- On a payroll register the employer is the buyer; leave seller empty.
- Use "" for anything not printed. Never guess a TIN."""

EXTRACT_PROMPT = """You are extracting accounting data from Philippine business documents for a bookkeeper.
The file may contain ONE or MANY separate documents (for example a scan of 40 receipts, one per page,
or one 3-page invoice). Return one entry per separate document.

Reply with ONLY valid JSON, no markdown fences, no explanation:
{"documents": [{
  "page_start": <first page of this document within this file, 1-based>,
  "page_end": <last page of this document, 1-based>,
  "document_title": "<title as printed, e.g. SALES INVOICE, OFFICIAL RECEIPT>",
  "kind": "<invoice|receipt|bir2307|payroll|import|statement|other>",
  "doc_number": "<invoice / receipt / serial number>",
  "date": "<YYYY-MM-DD>",
  "seller": {"name": "", "tin": "", "address": "", "vat_registered": <true if VAT REG TIN is printed, false if NON-VAT REG TIN, null if unclear>},
  "buyer": {"name": "", "tin": "", "address": ""},
  "gross_amount": <total amount due>,
  "vatable_amount": <VATable sales or purchase>,
  "vat_amount": <12% VAT shown>,
  "exempt_amount": <VAT-exempt amount>,
  "zero_rated_amount": <zero-rated amount>,
  "withholding_amount": <withholding tax deducted>,
  "nature": "<goods_for_resale|raw_materials|capital_goods|services|import|payroll|other>",
  "expense_account": "<purchases|raw_materials|importation|capital_goods|salaries|rent|utilities|professional_fees|office_supplies|representation|transportation|repairs|taxes_licenses|other>",
  "confidence": <0-100, your certainty in the amounts and date>
}]}

Rules:
- On a BIR Form 2307 the payee is the seller and the payor is the buyer; gross_amount is the total income payment and withholding_amount the total tax withheld.
- On a payroll register the employer is the buyer; gross_amount is total gross pay and withholding_amount total tax withheld.
- Meals or entertainment with clients use expense_account "representation".
- Amounts are plain numbers without currency symbols; use 0 when not shown.
- Use "" for text that is not printed. Never invent a TIN or a document number."""


@dataclass(frozen=True)
class Party:
    name: str = ""
    tin: str = ""          # 9-digit base, "" when unknown
    branch: str = "00000"
    address: str = ""


@dataclass(frozen=True)
class Detection:
    document_title: str
    kind: str
    seller: Party
    buyer: Party
    doc_date: date | None


@dataclass
class ExtractedDoc:
    page_start: int = 1
    page_end: int = 1
    document_title: str = ""
    kind: str = "other"
    doc_number: str = ""
    doc_date: date | None = None
    seller: Party = field(default_factory=Party)
    buyer: Party = field(default_factory=Party)
    seller_vat_registered: bool | None = None
    gross_amount: Decimal = Decimal("0.00")
    vatable_amount: Decimal = Decimal("0.00")
    vat_amount: Decimal = Decimal("0.00")
    exempt_amount: Decimal = Decimal("0.00")
    zero_rated_amount: Decimal = Decimal("0.00")
    withholding_amount: Decimal = Decimal("0.00")
    nature: str = "other"
    expense_account: str = "other"
    confidence: float = 0.0
    raw: dict = field(default_factory=dict)


def _load_json(raw: str):
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def _text(value, limit: int) -> str:
    return clean_text(str(value or ""))[:limit]


def _party(obj) -> Party:
    if not isinstance(obj, dict):
        return Party()
    tin, branch = normalize_tin(str(obj.get("tin") or ""))
    return Party(
        name=_text(obj.get("name"), 255),
        tin=tin,
        branch=branch or "00000",
        address=_text(obj.get("address"), 500),
    )


def _choice(value, allowed: tuple[str, ...]) -> str:
    text = str(value or "").strip().lower()
    return text if text in allowed else "other"


def _bool_or_none(value) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return value.strip().lower() == "true"
    return None


def _int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_detection(raw: str) -> Detection:
    """Parse the first-page detection reply. Never raises."""
    data = _load_json(raw)
    if not isinstance(data, dict):
        data = {}
    return Detection(
        document_title=_text(data.get("document_title"), 120),
        kind=_choice(data.get("kind"), KINDS),
        seller=_party(data.get("seller")),
        buyer=_party(data.get("buyer")),
        doc_date=parse_doc_date(data.get("date")),
    )


def parse_extraction(raw: str, page_offset: int = 0, chunk_pages: int | None = None) -> list[ExtractedDoc]:
    """Parse the extraction reply into documents with 1-based file-global pages. Never raises."""
    data = _load_json(raw)
    items = data.get("documents") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return []
    last_page = chunk_pages if chunk_pages and chunk_pages > 0 else None
    docs: list[ExtractedDoc] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        start = max(1, _int(item.get("page_start"), 1))
        end = max(start, _int(item.get("page_end"), start))
        if last_page is not None:
            start = min(start, last_page)
            end = min(max(end, start), last_page)
        try:
            confidence = float(item.get("confidence") or 0)
        except (TypeError, ValueError):
            confidence = 0.0
        seller_obj = item.get("seller") if isinstance(item.get("seller"), dict) else {}
        docs.append(ExtractedDoc(
            page_start=start + page_offset,
            page_end=end + page_offset,
            document_title=_text(item.get("document_title"), 120),
            kind=_choice(item.get("kind"), KINDS),
            doc_number=_text(item.get("doc_number"), 60),
            doc_date=parse_doc_date(item.get("date")),
            seller=_party(item.get("seller")),
            buyer=_party(item.get("buyer")),
            seller_vat_registered=_bool_or_none(seller_obj.get("vat_registered")),
            gross_amount=parse_money(item.get("gross_amount")),
            vatable_amount=parse_money(item.get("vatable_amount")),
            vat_amount=parse_money(item.get("vat_amount")),
            exempt_amount=parse_money(item.get("exempt_amount")),
            zero_rated_amount=parse_money(item.get("zero_rated_amount")),
            withholding_amount=parse_money(item.get("withholding_amount")),
            nature=_choice(item.get("nature"), NATURES),
            expense_account=_choice(item.get("expense_account"), EXPENSE_ACCOUNTS),
            confidence=min(100.0, max(0.0, confidence)),
            raw=item,
        ))
    return docs
```

Note on `test_parse_extraction_clamps_pages_to_chunk`: start=7 → clamped to 3; end=max(2, 7)=7 → `min(max(7,3),3)` = 3 ⇒ `(3, 3)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec -T backend python -m pytest tests/test_accounting_parsing.py tests/test_accounting_extraction.py -v`
Expected: PASS (11 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/accounting/parsing.py backend/app/services/accounting/extraction.py backend/tests/test_accounting_parsing.py backend/tests/test_accounting_extraction.py
git commit -m "feat(accounting): Gemini prompts and tolerant response parsing

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Company matching, upload grouping, classification

**Files:**
- Create: `backend/app/services/accounting/matching.py`, `backend/app/services/accounting/classify.py`
- Test: `backend/tests/test_accounting_matching.py`, `backend/tests/test_accounting_classify.py`

**Interfaces:**
- Consumes: `Party`, `ExtractedDoc`, `EXPENSE_ACCOUNTS` (Task 3); `period_for` (Task 2).
- Produces (matching):
  - `NAME_MATCH_THRESHOLD = 0.85`; `normalize_name(name: str) -> str`; `name_similarity(a: str, b: str) -> float`.
  - `CompanyCandidate(id: str, registered_name: str, tin: str = "", aliases: tuple[str, ...] = ())`.
  - `MatchResult(company_id: str | None, level: str, score: float, side: str | None)`; level ∈ `certain|likely|unknown`.
  - `match_company(seller: Party, buyer: Party, companies: list[CompanyCandidate]) -> MatchResult`.
  - `FileDetection(file_id: str, seller: Party, buyer: Party, match: MatchResult)`.
  - `UploadGroup(key: str, company_id: str | None, level: str, detected: Party, file_ids: list[str])`.
  - `suggest_groups(files: list[FileDetection]) -> list[UploadGroup]` (matched groups first, then by size).
  - `detection_json(detection: Detection, match: MatchResult) -> dict`; `file_detection_from_json(file_id: str, data: dict) -> FileDetection`.
- Produces (classify):
  - `CATEGORIES = ("sales", "purchases", "expenses", "payroll", "2307", "unsorted")`; `DOCUMENT_ACCOUNTS` (= `EXPENSE_ACCOUNTS` + `"sales"`, `"2307_received"`, `"2307_issued"`).
  - `CompanyProfile(tin: str, registered_name: str, aliases: tuple[str, ...], vat_registered: bool, fiscal_year_end_month: int)`.
  - `classify_document(ext: ExtractedDoc, company: CompanyProfile, rules: dict[str, tuple[str, str]], other_company_tins: frozenset[str]) -> dict` — keys are exactly `AADocument` column names (Task 5) minus ids/timestamps.
  - `empty_document_fields(page_count: int) -> dict` (same keys; category `unsorted`, reason `nothing_extracted`).
  - `mark_duplicate(fields: dict, seen: set[tuple[str, str]]) -> None` (mutates `fields`, updates `seen`).
  - `REVIEW_REASONS` tuple of all reason codes.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_accounting_matching.py`:

```python
from app.services.accounting.extraction import Detection, Party
from app.services.accounting.matching import (
    CompanyCandidate,
    FileDetection,
    MatchResult,
    detection_json,
    file_detection_from_json,
    match_company,
    normalize_name,
    suggest_groups,
)

JUAN = CompanyCandidate("c1", "Juan's Cloth Trading, Inc.", "123456789", ("JCT",))
MARIA = CompanyCandidate("c2", "Maria's Bakery", "987654321")


def test_normalize_name_strips_punctuation_and_legal_suffixes():
    assert normalize_name("Juan's Cloth Trading, Inc.") == "juans cloth trading"
    assert normalize_name("A & B Corp.") == "a and b"


def test_tin_match_is_certain_on_either_side():
    m = match_company(Party(name="Cebu Fabric", tin="111222333"), Party(tin="123456789"), [JUAN, MARIA])
    assert m == MatchResult("c1", "certain", 1.0, "buyer")
    m2 = match_company(Party(tin="987654321"), Party(), [JUAN, MARIA])
    assert (m2.company_id, m2.side) == ("c2", "seller")


def test_name_match_is_likely_and_uses_aliases():
    m = match_company(Party(name="Juans Cloth Trading"), Party(), [JUAN, MARIA])
    assert m.company_id == "c1" and m.level == "likely" and m.score >= 0.85
    assert match_company(Party(), Party(name="JCT"), [JUAN]).company_id == "c1"


def test_weak_name_match_is_unknown():
    m = match_company(Party(name="Jollibee Foods"), Party(), [JUAN, MARIA])
    assert m.company_id is None and m.level == "unknown"


def _fd(fid, seller=Party(), buyer=Party(), match=MatchResult(None, "unknown", 0.0, None)):
    return FileDetection(fid, seller, buyer, match)


def test_suggest_groups_groups_matched_and_unknown_files():
    certain = MatchResult("c1", "certain", 1.0, "buyer")
    likely = MatchResult("c1", "likely", 0.9, "buyer")
    new_co = Party(name="Reyes Logistics", tin="555666777")
    files = [
        _fd("f1", buyer=Party(tin="123456789"), match=certain),
        _fd("f2", buyer=Party(name="Juans Cloth"), match=likely),
        _fd("f3", seller=Party(name="Shell"), buyer=new_co),
        _fd("f4", seller=Party(name="Petron"), buyer=new_co),
        _fd("f5", seller=Party(name="Max's Restaurant")),
    ]
    groups = suggest_groups(files)
    assert [g.key for g in groups] == ["company:c1", "new:555666777", "new:"]
    assert groups[0].file_ids == ["f1", "f2"] and groups[0].level == "likely"
    assert groups[1].detected == new_co and groups[1].file_ids == ["f3", "f4"]
    assert groups[2].detected == Party() and groups[2].file_ids == ["f5"]


def test_frequent_seller_is_the_client_for_issued_invoices():
    client = Party(name="New Client Co", tin="444555666")
    files = [_fd("a", seller=client, buyer=Party(name="Buyer A")), _fd("b", seller=client, buyer=Party(name="Buyer B"))]
    [group] = suggest_groups(files)
    assert group.detected == client


def test_detection_json_round_trip_and_error_payload():
    det = Detection("SALES INVOICE", "invoice", Party(name="S", tin="111222333"), Party(name="B"), None)
    data = detection_json(det, MatchResult("c1", "likely", 0.9, "buyer"))
    fd = file_detection_from_json("f1", data)
    assert fd.seller == det.seller and fd.match.company_id == "c1" and fd.match.level == "likely"
    broken = file_detection_from_json("f2", {"error": "timeout"})
    assert broken.match.level == "unknown" and broken.seller == Party()
```

`backend/tests/test_accounting_classify.py`:

```python
from datetime import date
from decimal import Decimal

from app.models.accounting import AADocument
from app.services.accounting.classify import (
    CompanyProfile,
    classify_document,
    empty_document_fields,
    mark_duplicate,
)
from app.services.accounting.extraction import ExtractedDoc, Party

JUAN = CompanyProfile("123456789", "Juan's Cloth Trading", (), True, 12)
CLIENT = Party(name="Juan's Cloth Trading", tin="123456789")
SUPPLIER = Party(name="Cebu Fabric Supply", tin="111222333")


def _ext(**kw) -> ExtractedDoc:
    base = dict(
        document_title="SALES INVOICE", kind="invoice", doc_number="SI-1", doc_date=date(2026, 8, 14),
        seller=SUPPLIER, buyer=CLIENT, seller_vat_registered=True,
        gross_amount=Decimal("1120.00"), vatable_amount=Decimal("1000.00"), vat_amount=Decimal("120.00"),
        nature="raw_materials", expense_account="raw_materials", confidence=90.0,
    )
    base.update(kw)
    return ExtractedDoc(**base)


def test_fields_are_document_columns():
    columns = set(AADocument.__table__.columns.keys())
    assert set(classify_document(_ext(), JUAN, {}, frozenset())) <= columns
    assert set(empty_document_fields(3)) <= columns


def test_valid_purchase_invoice_needs_no_review():
    f = classify_document(_ext(), JUAN, {}, frozenset())
    assert f["category"] == "purchases" and f["account"] == "raw_materials"
    assert f["client_role"] == "buyer"
    assert f["vat_treatment"] == "vatable" and f["input_vat_valid"] is True
    assert f["review_reasons"] == [] and f["needs_review"] is False


def test_sales_invoice_issued_by_client():
    f = classify_document(_ext(seller=CLIENT, buyer=Party(name="Customer")), JUAN, {}, frozenset())
    assert f["category"] == "sales" and f["account"] == "sales" and f["client_role"] == "seller"
    assert f["input_vat_valid"] is None


def test_official_receipt_not_addressed_to_client_loses_input_vat():
    ext = _ext(document_title="OFFICIAL RECEIPT", kind="receipt", buyer=Party(),
               seller=Party(name="Max's Restaurant", tin="222333444"),
               nature="services", expense_account="representation")
    f = classify_document(ext, JUAN, {}, frozenset())
    assert f["category"] == "expenses" and f["account"] == "representation"
    assert f["vat_treatment"] == "no_input_vat" and f["input_vat_valid"] is False
    assert "not_an_invoice" in f["review_reasons"]
    assert "not_addressed_to_client" in f["review_reasons"]
    assert f["needs_review"] is True


def test_vat_math_mismatch_flagged():
    f = classify_document(_ext(vat_amount=Decimal("200.00")), JUAN, {}, frozenset())
    assert "vat_math_mismatch" in f["review_reasons"]


def test_vatable_amount_derived_when_missing():
    f = classify_document(_ext(vatable_amount=Decimal("0.00")), JUAN, {}, frozenset())
    assert f["vatable_amount"] == Decimal("1000.00")
    assert "vat_math_mismatch" not in f["review_reasons"]


def test_non_vat_company_skips_input_vat_checks():
    non_vat = CompanyProfile("123456789", "Juan's Cloth Trading", (), False, 12)
    f = classify_document(_ext(document_title="OFFICIAL RECEIPT"), non_vat, {}, frozenset())
    assert "not_an_invoice" not in f["review_reasons"]
    assert f["input_vat_valid"] is None


def test_supplier_rule_overrides_category_and_account():
    rules = {"111222333": ("expenses", "office_supplies")}
    f = classify_document(_ext(), JUAN, rules, frozenset())
    assert (f["category"], f["account"]) == ("expenses", "office_supplies")


def test_other_company_tin_flagged():
    ext = _ext(buyer=Party(name="Maria's Bakery", tin="987654321"))
    f = classify_document(ext, JUAN, {}, frozenset({"987654321"}))
    assert "other_company_tin" in f["review_reasons"]


def test_low_confidence_and_unreadable_go_to_review_or_unsorted():
    low = classify_document(_ext(confidence=60.0), JUAN, {}, frozenset())
    assert "low_confidence" in low["review_reasons"] and low["category"] == "purchases"
    junk = classify_document(_ext(kind="other", confidence=20.0), JUAN, {}, frozenset())
    assert junk["category"] == "unsorted" and "unsorted" in junk["review_reasons"]


def test_period_follows_document_date_and_fiscal_year():
    june_fye = CompanyProfile("123456789", "Juan's Cloth Trading", (), True, 6)
    f = classify_document(_ext(doc_date=date(2026, 7, 2)), june_fye, {}, frozenset())
    assert (f["period_year"], f["period_quarter"], f["period_month"]) == (2027, 1, 1)
    undated = classify_document(_ext(doc_date=None), JUAN, {}, frozenset())
    assert undated["period_year"] is None and "missing_date" in undated["review_reasons"]


def test_2307_and_payroll_categories():
    f = classify_document(_ext(kind="bir2307", seller=CLIENT, buyer=SUPPLIER), JUAN, {}, frozenset())
    assert (f["category"], f["account"]) == ("2307", "2307_received")
    p = classify_document(_ext(kind="payroll", seller=Party(), nature="payroll"), JUAN, {}, frozenset())
    assert (p["category"], p["account"]) == ("payroll", "salaries")


def test_empty_document_fields():
    f = empty_document_fields(4)
    assert (f["page_start"], f["page_end"]) == (1, 4)
    assert f["category"] == "unsorted" and f["review_reasons"] == ["nothing_extracted"]


def test_mark_duplicate_flags_second_copy():
    seen: set[tuple[str, str]] = set()
    first = classify_document(_ext(), JUAN, {}, frozenset())
    second = classify_document(_ext(doc_number="si-1 "), JUAN, {}, frozenset())
    mark_duplicate(first, seen)
    mark_duplicate(second, seen)
    assert "possible_duplicate" not in first["review_reasons"]
    assert "possible_duplicate" in second["review_reasons"] and second["needs_review"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec -T backend python -m pytest tests/test_accounting_matching.py -v`
Expected: FAIL with `ModuleNotFoundError: ... matching`. (`test_accounting_classify.py` also imports `app.models.accounting` from Task 5 — it is run in Task 5, Step 4.)

- [ ] **Step 3: Implement**

`backend/app/services/accounting/matching.py`:

```python
"""Match a document's parties to the firm's company databank (pure)."""

import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher

from app.services.accounting.extraction import Detection, Party

NAME_MATCH_THRESHOLD = 0.85
_LEVELS = ("certain", "likely", "unknown")
_LEGAL_SUFFIXES = frozenset(
    {"inc", "incorporated", "corp", "corporation", "co", "company", "ltd", "limited", "opc", "llc"}
)


def normalize_name(name: str) -> str:
    text = (name or "").lower().replace("&", " and ")
    text = re.sub(r"['’`.]", "", text)
    tokens = [t for t in re.split(r"[^a-z0-9]+", text) if t and t not in _LEGAL_SUFFIXES]
    return " ".join(tokens)


def name_similarity(a: str, b: str) -> float:
    na, nb = normalize_name(a), normalize_name(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


@dataclass(frozen=True)
class CompanyCandidate:
    id: str
    registered_name: str
    tin: str = ""
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class MatchResult:
    company_id: str | None
    level: str          # certain | likely | unknown
    score: float
    side: str | None    # seller | buyer


def match_company(seller: Party, buyer: Party, companies: list[CompanyCandidate]) -> MatchResult:
    """Exact TIN on either side wins; otherwise the best fuzzy name match ≥ threshold."""
    sides = (("seller", seller), ("buyer", buyer))
    for side, party in sides:
        if party.tin:
            for c in companies:
                if c.tin and c.tin == party.tin:
                    return MatchResult(c.id, "certain", 1.0, side)
    best = MatchResult(None, "unknown", 0.0, None)
    for side, party in sides:
        if not party.name:
            continue
        for c in companies:
            score = max(name_similarity(party.name, n) for n in (c.registered_name, *c.aliases))
            if score > best.score:
                best = MatchResult(c.id, "likely", score, side)
    if best.score >= NAME_MATCH_THRESHOLD:
        return best
    return MatchResult(None, "unknown", best.score, None)


@dataclass(frozen=True)
class FileDetection:
    file_id: str
    seller: Party
    buyer: Party
    match: MatchResult


@dataclass
class UploadGroup:
    key: str
    company_id: str | None
    level: str
    detected: Party
    file_ids: list[str] = field(default_factory=list)


def _party_key(p: Party) -> str:
    return p.tin or normalize_name(p.name)


def _client_party(f: FileDetection, freq: Counter) -> Party:
    """Guess which party of an unmatched file is the client.

    A party seen on ≥2 unmatched files in the drop is the client (a drop is
    usually one client's papers). Otherwise the buyer, since receipts outnumber
    issued invoices; a file with no buyer gives no guess.
    """
    candidates = [p for p in (f.buyer, f.seller) if _party_key(p)]
    if not candidates:
        return Party()
    best = max(candidates, key=lambda p: freq[_party_key(p)])
    if freq[_party_key(best)] >= 2:
        return best
    return f.buyer if _party_key(f.buyer) else Party()


def suggest_groups(files: list[FileDetection]) -> list[UploadGroup]:
    unmatched = [f for f in files if f.match.company_id is None]
    freq: Counter = Counter(
        k for f in unmatched for k in {_party_key(f.seller), _party_key(f.buyer)} if k
    )
    groups: dict[str, UploadGroup] = {}
    for f in files:
        if f.match.company_id is not None:
            key = f"company:{f.match.company_id}"
            party = f.seller if f.match.side == "seller" else f.buyer
            group = groups.setdefault(key, UploadGroup(key, f.match.company_id, f.match.level, party))
            if f.match.level == "likely":
                group.level = "likely"
        else:
            client = _client_party(f, freq)
            pk = _party_key(client)
            key = f"new:{pk}"
            group = groups.setdefault(key, UploadGroup(key, None, "unknown", client))
        group.file_ids.append(f.file_id)
    return sorted(groups.values(), key=lambda g: (g.company_id is None, -len(g.file_ids)))


def detection_json(detection: Detection, match: MatchResult) -> dict:
    return {
        "document_title": detection.document_title,
        "kind": detection.kind,
        "seller": asdict(detection.seller),
        "buyer": asdict(detection.buyer),
        "date": detection.doc_date.isoformat() if detection.doc_date else None,
        "match": asdict(match),
    }


def _party_from_json(data) -> Party:
    d = data if isinstance(data, dict) else {}
    return Party(
        name=str(d.get("name") or ""),
        tin=str(d.get("tin") or ""),
        branch=str(d.get("branch") or "00000"),
        address=str(d.get("address") or ""),
    )


def file_detection_from_json(file_id: str, data: dict) -> FileDetection:
    data = data if isinstance(data, dict) else {}
    m = data.get("match") if isinstance(data.get("match"), dict) else {}
    level = m.get("level") if m.get("level") in _LEVELS else "unknown"
    company_id = m.get("company_id") if level != "unknown" else None
    try:
        score = float(m.get("score") or 0)
    except (TypeError, ValueError):
        score = 0.0
    match = MatchResult(company_id, level if company_id else "unknown", score, m.get("side"))
    return FileDetection(file_id, _party_from_json(data.get("seller")), _party_from_json(data.get("buyer")), match)
```

Ordering check for `test_suggest_groups_groups_matched_and_unknown_files`: `company:c1` (2 files, matched) first; then the two unmatched groups by size: `new:555666777` (2) before `new:` (1). The Max's Restaurant file: its only party is the seller with freq 1, no buyer → `Party()` → key `new:`.

`backend/app/services/accounting/classify.py`:

```python
"""Turn one extracted document into AutoAccounting document fields (pure)."""

from dataclasses import dataclass
from decimal import Decimal

from app.services.accounting.extraction import EXPENSE_ACCOUNTS, ExtractedDoc
from app.services.accounting.matching import NAME_MATCH_THRESHOLD, name_similarity
from app.services.accounting.periods import period_for

CATEGORIES = ("sales", "purchases", "expenses", "payroll", "2307", "unsorted")
DOCUMENT_ACCOUNTS = EXPENSE_ACCOUNTS + ("sales", "2307_received", "2307_issued")
REVIEW_REASONS = (
    "low_confidence", "missing_date", "missing_amount", "unsorted", "not_addressed_to_client",
    "seller_not_vat_registered", "not_an_invoice", "vat_math_mismatch", "possible_duplicate",
    "other_company_tin", "nothing_extracted",
)

LOW_CONFIDENCE = 70.0
UNSORTED_CONFIDENCE = 40.0
_ROLE_NAME_THRESHOLD = 0.6
_PURCHASE_NATURES = frozenset({"goods_for_resale", "raw_materials", "import"})
_VAT_RATE = Decimal("0.12")
_VAT_TOLERANCE = Decimal("1.00")
_ZERO = Decimal("0.00")


@dataclass(frozen=True)
class CompanyProfile:
    tin: str
    registered_name: str
    aliases: tuple[str, ...]
    vat_registered: bool
    fiscal_year_end_month: int


def _name_score(name: str, company: CompanyProfile) -> float:
    return max(name_similarity(name, n) for n in (company.registered_name, *company.aliases))


def client_role(ext: ExtractedDoc, company: CompanyProfile) -> str:
    """'seller' when the client issued the document, else 'buyer'."""
    if company.tin:
        if ext.seller.tin == company.tin:
            return "seller"
        if ext.buyer.tin == company.tin:
            return "buyer"
    seller_score = _name_score(ext.seller.name, company)
    buyer_score = _name_score(ext.buyer.name, company)
    if seller_score >= _ROLE_NAME_THRESHOLD and seller_score > buyer_score:
        return "seller"
    return "buyer"


def _category(ext: ExtractedDoc, role: str) -> str:
    if ext.kind in ("other", "statement") or ext.confidence < UNSORTED_CONFIDENCE:
        return "unsorted"
    if ext.kind == "bir2307":
        return "2307"
    if ext.kind == "payroll" or ext.nature == "payroll":
        return "payroll"
    if role == "seller":
        return "sales"
    if ext.nature in _PURCHASE_NATURES or ext.kind == "import":
        return "purchases"
    return "expenses"


def _account(ext: ExtractedDoc, category: str, role: str) -> str:
    if category == "sales":
        return "sales"
    if category == "2307":
        return "2307_received" if role == "seller" else "2307_issued"
    if category == "payroll":
        return "salaries"
    if category == "purchases":
        return {"raw_materials": "raw_materials", "import": "importation"}.get(ext.nature, "purchases")
    return ext.expense_account or "other"


def _vatable(ext: ExtractedDoc) -> Decimal:
    """VATable base; derived from the total when the document only prints VAT."""
    if ext.vatable_amount > 0 or ext.vat_amount <= 0:
        return ext.vatable_amount
    derived = ext.gross_amount - ext.vat_amount - ext.exempt_amount - ext.zero_rated_amount
    return derived if derived > 0 else _ZERO


def _vat_math_mismatch(vatable: Decimal, vat: Decimal) -> bool:
    if vat <= 0:
        return False
    return abs(vatable * _VAT_RATE - vat) > _VAT_TOLERANCE


def _input_vat_issues(ext: ExtractedDoc, company: CompanyProfile, vatable: Decimal) -> list[str]:
    issues: list[str] = []
    addressed = bool(company.tin and ext.buyer.tin == company.tin) or (
        _name_score(ext.buyer.name, company) >= NAME_MATCH_THRESHOLD
    )
    if not addressed:
        issues.append("not_addressed_to_client")
    if ext.seller_vat_registered is not True:
        issues.append("seller_not_vat_registered")
    if "INVOICE" not in ext.document_title.upper():
        issues.append("not_an_invoice")
    if _vat_math_mismatch(vatable, ext.vat_amount):
        issues.append("vat_math_mismatch")
    return issues


def _treatment(ext: ExtractedDoc) -> str:
    if ext.vat_amount > 0:
        return "vatable"
    if ext.zero_rated_amount > 0:
        return "zero_rated"
    if ext.exempt_amount > 0:
        return "exempt"
    return ""


def classify_document(
    ext: ExtractedDoc,
    company: CompanyProfile,
    rules: dict[str, tuple[str, str]],
    other_company_tins: frozenset[str],
) -> dict:
    """Field values for one ``aa_documents`` row (without ids/timestamps)."""
    role = client_role(ext, company)
    counterparty = ext.buyer if role == "seller" else ext.seller
    client_party = ext.seller if role == "seller" else ext.buyer

    category = _category(ext, role)
    account = _account(ext, category, role)
    rule = rules.get(counterparty.tin) if counterparty.tin else None
    if rule and category in ("purchases", "expenses") and rule[0] in ("purchases", "expenses"):
        category, account = rule

    vatable = _vatable(ext)
    reasons: list[str] = []
    if ext.confidence < LOW_CONFIDENCE:
        reasons.append("low_confidence")
    if ext.doc_date is None:
        reasons.append("missing_date")
    if ext.gross_amount <= 0:
        reasons.append("missing_amount")
    if category == "unsorted":
        reasons.append("unsorted")

    treatment = _treatment(ext)
    input_vat_valid: bool | None = None
    if role == "buyer" and category in ("purchases", "expenses") and company.vat_registered and ext.vat_amount > 0:
        issues = _input_vat_issues(ext, company, vatable)
        input_vat_valid = not issues
        reasons.extend(issues)
        if issues:
            treatment = "no_input_vat"
    elif _vat_math_mismatch(vatable, ext.vat_amount):
        reasons.append("vat_math_mismatch")

    if client_party.tin and client_party.tin != company.tin and client_party.tin in other_company_tins:
        reasons.append("other_company_tin")

    period = period_for(ext.doc_date, company.fiscal_year_end_month) if ext.doc_date else None
    return {
        "page_start": ext.page_start,
        "page_end": ext.page_end,
        "document_title": ext.document_title[:120],
        "doc_type": ext.kind,
        "category": category,
        "account": account,
        "client_role": role,
        "doc_number": ext.doc_number[:60],
        "doc_date": ext.doc_date,
        "period_year": period.fiscal_year if period else None,
        "period_quarter": period.quarter if period else None,
        "period_month": period.month_in_quarter if period else None,
        "seller_name": ext.seller.name,
        "seller_tin": ext.seller.tin,
        "seller_address": ext.seller.address,
        "seller_vat_registered": ext.seller_vat_registered,
        "buyer_name": ext.buyer.name,
        "buyer_tin": ext.buyer.tin,
        "buyer_address": ext.buyer.address,
        "gross_amount": ext.gross_amount,
        "vatable_amount": vatable,
        "vat_amount": ext.vat_amount,
        "exempt_amount": ext.exempt_amount,
        "zero_rated_amount": ext.zero_rated_amount,
        "withholding_amount": ext.withholding_amount,
        "vat_treatment": treatment,
        "input_vat_valid": input_vat_valid,
        "confidence": ext.confidence,
        "review_reasons": reasons,
        "needs_review": bool(reasons),
        "raw": ext.raw,
    }


def empty_document_fields(page_count: int) -> dict:
    """Placeholder row for a file Gemini returned nothing for, so it is never lost."""
    fields = classify_document(
        ExtractedDoc(page_start=1, page_end=max(1, page_count), kind="other"),
        CompanyProfile("", "", (), False, 12),
        {},
        frozenset(),
    )
    fields.update(review_reasons=["nothing_extracted"], needs_review=True, raw=None)
    return fields


def mark_duplicate(fields: dict, seen: set[tuple[str, str]]) -> None:
    """Flag a document whose seller TIN + document number was already filed."""
    number = (fields.get("doc_number") or "").strip().upper()
    if not number:
        return
    key = (fields.get("seller_tin") or "", number)
    if key in seen:
        fields["review_reasons"].append("possible_duplicate")
        fields["needs_review"] = True
    seen.add(key)
```

- [ ] **Step 4: Run matching tests to verify they pass**

Run: `docker compose exec -T backend python -m pytest tests/test_accounting_matching.py -v`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/accounting/matching.py backend/app/services/accounting/classify.py backend/tests/test_accounting_matching.py backend/tests/test_accounting_classify.py
git commit -m "feat(accounting): company matching, upload grouping, document classification

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Models, migrations, tree assembly

**Files:**
- Create: `backend/app/models/accounting.py`, `backend/app/services/accounting/tree.py`
- Modify: `backend/app/main.py` (model import block ~line 27-37), `backend/app/startup_migrations.py` (end of `_run_migrations`)
- Test: `backend/tests/test_accounting_tree.py` (+ runs `test_accounting_classify.py` from Task 4)

**Interfaces:**
- Produces: ORM classes `AACompany`, `AAUpload`, `AAFile`, `AADocument`, `AASupplierRule` (tables `aa_companies`, `aa_uploads`, `aa_files`, `aa_documents`, `aa_supplier_rules`); status strings — upload: `detecting|awaiting_confirmation|extracting|done|failed`; file: `uploaded|duplicate|detected|skipped|extracting|extracted|error`.
- Produces (tree): `TreeCompanyInput(id: str, registered_name: str, tin: str, pinned: bool, fiscal_year_end_month: int)`; `build_tree(companies: list[TreeCompanyInput], rows: list[tuple]) -> list[dict]` where rows are `(company_id, year | None, quarter | None, document_count, review_count)`; `folder_counts(items: list[tuple[str, bool, bool, bool]]) -> dict[str, int]` from `(category, needs_review, reviewed, excluded)`.

- [ ] **Step 1: Write the failing test** — `backend/tests/test_accounting_tree.py`:

```python
import uuid

from app.services.accounting.tree import TreeCompanyInput, build_tree, folder_counts

A, B = str(uuid.uuid4()), str(uuid.uuid4())


def test_build_tree_nests_years_and_quarters_newest_first():
    companies = [
        TreeCompanyInput(A, "Juan's Cloth Trading", "123456789", True, 12),
        TreeCompanyInput(B, "Maria's Bakery", "987654321", False, 6),
    ]
    rows = [
        (uuid.UUID(A), 2026, 2, 10, 0),
        (uuid.UUID(A), 2026, 3, 48, 5),
        (uuid.UUID(A), 2025, 4, 7, None),
        (uuid.UUID(A), None, None, 2, 2),
        (uuid.uuid4(), 2026, 1, 1, 0),  # company not in list → ignored
    ]
    tree = build_tree(companies, rows)
    juan, maria = tree
    assert [y["year"] for y in juan["years"]] == [2026, 2025]
    assert [q["quarter"] for q in juan["years"][0]["quarters"]] == [3, 2]
    assert juan["years"][0]["quarters"][0] == {
        "year": 2026, "quarter": 3, "label": "Q3 (Jul–Sep)", "document_count": 48, "review_count": 5,
    }
    assert juan["years"][1]["quarters"][0]["review_count"] == 0
    assert juan["undated_count"] == 2
    assert maria["years"] == [] and maria["undated_count"] == 0 and maria["fiscal_year_end_month"] == 6


def test_folder_counts_skip_excluded_and_count_open_reviews():
    counts = folder_counts([
        ("sales", False, False, False),
        ("purchases", True, False, False),
        ("purchases", True, True, False),
        ("expenses", True, False, True),
    ])
    assert counts["sales"] == 1 and counts["purchases"] == 2 and counts["expenses"] == 0
    assert counts["review"] == 1
    assert counts["unsorted"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec -T backend python -m pytest tests/test_accounting_tree.py tests/test_accounting_classify.py -v`
Expected: FAIL with `ModuleNotFoundError` (`tree`, `app.models.accounting`).

- [ ] **Step 3: Implement**

`backend/app/models/accounting.py`:

```python
"""AutoAccounting phase 1 tables: company databank, uploads, files, documents."""

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Boolean, Date, DateTime, Float, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _money():
    return mapped_column(Numeric(14, 2), nullable=False, default=Decimal("0.00"), server_default="0")


def _created():
    return mapped_column(DateTime(timezone=True), nullable=False, default=_now)


def _updated():
    return mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)


class AACompany(Base):
    """A client company in a firm's databank."""

    __tablename__ = "aa_companies"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    registered_name: Mapped[str] = mapped_column(String(255), nullable=False)
    aliases: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    tin: Mapped[str] = mapped_column(String(9), nullable=False, default="")
    branch_code: Mapped[str] = mapped_column(String(5), nullable=False, default="00000")
    rdo_code: Mapped[str] = mapped_column(String(5), nullable=False, default="")
    address: Mapped[str] = mapped_column(Text, nullable=False, default="")
    zip_code: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    taxpayer_type: Mapped[str] = mapped_column(String(20), nullable=False, default="corporation")
    vat_status: Mapped[str] = mapped_column(String(10), nullable=False, default="vat")
    income_tax_option: Mapped[str] = mapped_column(String(15), nullable=False, default="graduated")
    deduction_method: Mapped[str] = mapped_column(String(10), nullable=False, default="itemized")
    business_type: Mapped[str] = mapped_column(String(15), nullable=False, default="trading")
    is_withholding_agent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_top_withholding_agent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    has_employees: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    fiscal_year_end_month: Mapped[int] = mapped_column(Integer, nullable=False, default=12)
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class AAUpload(Base):
    """One drop of files; drives the detect → confirm → extract flow."""

    __tablename__ = "aa_uploads"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    uploaded_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    preselected_company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("aa_companies.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="detecting")
    total_files: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed_files: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class AAFile(Base):
    """A physical uploaded file (may hold many documents)."""

    __tablename__ = "aa_files"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    upload_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("aa_uploads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("aa_companies.id", ondelete="SET NULL"), nullable=True, index=True
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_type: Mapped[str] = mapped_column(String(10), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="uploaded")
    detection: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    pages_charged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = _created()


class AADocument(Base):
    """One logical document (receipt, invoice, 2307 …) extracted from a file."""

    __tablename__ = "aa_documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("aa_companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("aa_files.id", ondelete="CASCADE"), nullable=False, index=True
    )
    page_start: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    page_end: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    document_title: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    doc_type: Mapped[str] = mapped_column(String(20), nullable=False, default="other")
    category: Mapped[str] = mapped_column(String(20), nullable=False, default="unsorted")
    account: Mapped[str] = mapped_column(String(40), nullable=False, default="other")
    client_role: Mapped[str] = mapped_column(String(10), nullable=False, default="buyer")
    doc_number: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    doc_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    period_quarter: Mapped[int | None] = mapped_column(Integer, nullable=True)
    period_month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    period_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    seller_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    seller_tin: Mapped[str] = mapped_column(String(9), nullable=False, default="")
    seller_address: Mapped[str] = mapped_column(Text, nullable=False, default="")
    seller_vat_registered: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    buyer_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    buyer_tin: Mapped[str] = mapped_column(String(9), nullable=False, default="")
    buyer_address: Mapped[str] = mapped_column(Text, nullable=False, default="")
    gross_amount: Mapped[Decimal] = _money()
    vatable_amount: Mapped[Decimal] = _money()
    vat_amount: Mapped[Decimal] = _money()
    exempt_amount: Mapped[Decimal] = _money()
    zero_rated_amount: Mapped[Decimal] = _money()
    withholding_amount: Mapped[Decimal] = _money()
    vat_treatment: Mapped[str] = mapped_column(String(15), nullable=False, default="")
    input_vat_valid: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    review_reasons: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    reviewed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    excluded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    raw: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class AASupplierRule(Base):
    """Remembered category/account for a counterparty, learned from corrections."""

    __tablename__ = "aa_supplier_rules"
    __table_args__ = (UniqueConstraint("company_id", "counterparty_tin", name="uq_aa_supplier_rule"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("aa_companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    counterparty_tin: Mapped[str] = mapped_column(String(9), nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    account: Mapped[str] = mapped_column(String(40), nullable=False)
    updated_at: Mapped[datetime] = _updated()
```

`backend/app/services/accounting/tree.py`:

```python
"""Folder-tree assembly for the AutoAccounting browser (pure)."""

from dataclasses import dataclass

from app.services.accounting.classify import CATEGORIES
from app.services.accounting.periods import quarter_label


@dataclass(frozen=True)
class TreeCompanyInput:
    id: str
    registered_name: str
    tin: str
    pinned: bool
    fiscal_year_end_month: int


def build_tree(companies: list[TreeCompanyInput], rows: list[tuple]) -> list[dict]:
    """Nest per-period document counts under each company.

    ``rows`` are ``(company_id, year | None, quarter | None, document_count, review_count)``.
    Company order is preserved; years and quarters are newest first.
    """
    nodes: dict[str, dict] = {
        c.id: {"company": c, "years": {}, "undated_count": 0} for c in companies
    }
    for company_id, year, quarter, count, review in rows:
        node = nodes.get(str(company_id))
        if node is None:
            continue
        if year is None or quarter is None:
            node["undated_count"] += int(count)
            continue
        node["years"].setdefault(year, []).append({
            "year": year,
            "quarter": quarter,
            "label": quarter_label(quarter, node["company"].fiscal_year_end_month),
            "document_count": int(count),
            "review_count": int(review or 0),
        })
    out = []
    for node in nodes.values():
        c = node["company"]
        out.append({
            "id": c.id,
            "registered_name": c.registered_name,
            "tin": c.tin,
            "pinned": c.pinned,
            "fiscal_year_end_month": c.fiscal_year_end_month,
            "years": [
                {"year": y, "quarters": sorted(qs, key=lambda q: -q["quarter"])}
                for y, qs in sorted(node["years"].items(), reverse=True)
            ],
            "undated_count": node["undated_count"],
        })
    return out


def folder_counts(items: list[tuple[str, bool, bool, bool]]) -> dict[str, int]:
    """Per-category counts plus open reviews, from ``(category, needs_review, reviewed, excluded)``."""
    counts = {c: 0 for c in CATEGORIES}
    counts["review"] = 0
    for category, needs_review, reviewed, excluded in items:
        if excluded:
            continue
        counts[category] = counts.get(category, 0) + 1
        if needs_review and not reviewed:
            counts["review"] += 1
    return counts
```

`backend/app/main.py` — add beside the other model registrations (after line 37):

```python
from app.models import accounting  # noqa: F401  # registers aa_* tables
```

`backend/app/startup_migrations.py` — append at the end of `_run_migrations` (after the `uq_invoice_payment_open` index):

```python
    # AutoAccounting (2026-10-05). Tables come from create_all; these are the
    # partial/compound indexes create_all can't express, and the feature ships
    # dark until the owner turns the toggle on.
    await _create_index_if_missing(
        conn,
        'CREATE UNIQUE INDEX IF NOT EXISTS "uq_aa_companies_tin" '
        'ON "aa_companies" ("enterprise_id", "tin", "branch_code") WHERE tin <> \'\'',
    )
    await _create_index_if_missing(
        conn,
        'CREATE INDEX IF NOT EXISTS "ix_aa_documents_period" '
        'ON "aa_documents" ("company_id", "period_year", "period_quarter")',
    )
    await _create_index_if_missing(
        conn,
        'CREATE INDEX IF NOT EXISTS "ix_aa_files_enterprise_sha" ON "aa_files" ("enterprise_id", "sha256")',
    )
    await conn.execute(text(
        "INSERT INTO feature_toggles (key, enabled, updated_at) "
        "VALUES ('accounting', false, now()) ON CONFLICT (key) DO NOTHING"
    ))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec -T backend python -m pytest tests/test_accounting_tree.py tests/test_accounting_classify.py -v`
Expected: PASS (2 + 14 tests).

- [ ] **Step 5: Verify the schema boots**

Run: `docker compose restart backend && sleep 8 && docker compose logs --tail=40 backend`
Expected: no traceback; startup completes.
Run: `docker compose exec -T db psql -U snagstock -d snagstock -c "\dt aa_*" -c "select key, enabled from feature_toggles where key='accounting'"`
Expected: 5 `aa_*` tables listed; one row `accounting | f`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/accounting.py backend/app/services/accounting/tree.py backend/app/main.py backend/app/startup_migrations.py backend/tests/test_accounting_tree.py
git commit -m "feat(accounting): aa_* tables, startup indexes, folder tree assembly

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Schemas and upload storage

**Files:**
- Create: `backend/app/schemas/accounting.py`, `backend/app/services/accounting/storage.py`
- Test: `backend/tests/test_accounting_schemas.py`, `backend/tests/test_accounting_storage.py`

**Interfaces:**
- Consumes: `normalize_tin` (Task 3); `validate_file`; `gemini_service.get_pdf_page_count_safe`.
- Produces (schemas): `CompanyIn`, `CompanyOut`, `CompanyBrief`, `UploadFileOut`, `UploadGroupOut`, `UploadOut`, `ConfirmAssignment`, `ConfirmIn`, `TreeQuarterOut`, `TreeYearOut`, `TreeCompanyOut`, `DocumentOut`, `FolderOut`, `DocumentPatch` (fields as written below).
- Produces (storage): `ALLOWED_EXTS: dict[str, str]`; `class UploadRejected(ValueError)`; `StoredUpload(filename: str, stored_path: str, size: int, sha256: str, file_type: str, page_count: int)`; `upload_dir(upload_id: uuid.UUID) -> Path`; `async stream_upload(f: UploadFile, dest_dir: Path) -> StoredUpload`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_accounting_schemas.py`:

```python
import pytest
from pydantic import ValidationError

from app.schemas.accounting import CompanyIn, ConfirmAssignment, DocumentPatch


def test_company_tin_normalised_and_required():
    c = CompanyIn(registered_name="Juan's Cloth Trading", tin="123-456-789-000")
    assert c.tin == "123456789" and c.branch_code == "00000"
    with pytest.raises(ValidationError):
        CompanyIn(registered_name="X", tin="12345")


def test_eight_percent_only_for_individuals():
    with pytest.raises(ValidationError):
        CompanyIn(registered_name="X Corp", tin="123456789", income_tax_option="eight_percent")
    ok = CompanyIn(registered_name="Juan", tin="123456789", taxpayer_type="individual",
                   income_tax_option="eight_percent")
    assert ok.income_tax_option == "eight_percent"


def test_branch_code_zero_padded():
    assert CompanyIn(registered_name="X", tin="123456789", branch_code="1").branch_code == "00001"


def test_confirm_assignment_needs_exactly_one_target():
    import uuid
    fid = uuid.uuid4()
    with pytest.raises(ValidationError):
        ConfirmAssignment(file_ids=[fid])
    with pytest.raises(ValidationError):
        ConfirmAssignment(file_ids=[fid], company_id=uuid.uuid4(), skip=True)
    assert ConfirmAssignment(file_ids=[fid], skip=True).skip is True


def test_document_patch_period_pair_and_tins():
    with pytest.raises(ValidationError):
        DocumentPatch(period_year=2026)
    p = DocumentPatch(period_year=None, period_quarter=None, seller_tin="111-222-333-000")
    assert {"period_year", "period_quarter"} <= p.model_fields_set
    assert p.seller_tin == "111222333"
    with pytest.raises(ValidationError):
        DocumentPatch(category="nonsense")
    with pytest.raises(ValidationError):
        DocumentPatch(unknown_field=1)
```

`backend/tests/test_accounting_storage.py`:

```python
import asyncio
import io

import fitz
import pytest
from starlette.datastructures import UploadFile

from app.services.accounting.storage import UploadRejected, stream_upload


def _upload(name: str, data: bytes) -> UploadFile:
    return UploadFile(file=io.BytesIO(data), filename=name)


def _pdf_bytes(pages: int = 2) -> bytes:
    doc = fitz.open()
    for _ in range(pages):
        doc.new_page()
    data = doc.tobytes()
    doc.close()
    return data


def test_stream_upload_stores_pdf_with_hash_and_pages(tmp_path):
    stored = asyncio.run(stream_upload(_upload("scan.pdf", _pdf_bytes(2)), tmp_path))
    assert stored.file_type == "pdf" and stored.page_count == 2
    assert len(stored.sha256) == 64 and stored.size > 0
    assert stored.stored_path.startswith(str(tmp_path))


def test_stream_upload_rejects_wrong_extension(tmp_path):
    with pytest.raises(UploadRejected, match="only PDF, PNG and JPG"):
        asyncio.run(stream_upload(_upload("sales.xlsx", b"PK\x03\x04data"), tmp_path))


def test_stream_upload_rejects_empty(tmp_path):
    with pytest.raises(UploadRejected, match="is empty"):
        asyncio.run(stream_upload(_upload("blank.pdf", b""), tmp_path))
    assert list(tmp_path.iterdir()) == []


def test_stream_upload_rejects_unreadable_pdf(tmp_path):
    with pytest.raises(UploadRejected, match="couldn't be opened"):
        asyncio.run(stream_upload(_upload("broken.pdf", b"%PDF-1.4 this is not really a pdf"), tmp_path))
    assert list(tmp_path.iterdir()) == []


def test_stream_upload_rejects_mismatched_magic(tmp_path):
    with pytest.raises(UploadRejected):
        asyncio.run(stream_upload(_upload("photo.png", b"GIF89a....."), tmp_path))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec -T backend python -m pytest tests/test_accounting_schemas.py tests/test_accounting_storage.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`backend/app/schemas/accounting.py`:

```python
"""Request/response models for /api/accounting."""

import re
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.services.accounting.parsing import normalize_tin

Category = Literal["sales", "purchases", "expenses", "payroll", "2307", "unsorted"]
Account = Literal[
    "purchases", "raw_materials", "importation", "capital_goods", "salaries", "rent",
    "utilities", "professional_fees", "office_supplies", "representation", "transportation",
    "repairs", "taxes_licenses", "other", "sales", "2307_received", "2307_issued",
]
VatTreatment = Literal["", "vatable", "exempt", "zero_rated", "no_input_vat"]
def _money_field():
    return Field(default=None, max_digits=14, decimal_places=2)


def _tin_base(value: str) -> str:
    base, _ = normalize_tin(value)
    if not base:
        raise ValueError("TIN needs at least 9 digits")
    return base


class CompanyIn(BaseModel):
    registered_name: str = Field(min_length=1, max_length=255)
    aliases: list[str] = Field(default_factory=list, max_length=20)
    tin: str = Field(min_length=9, max_length=25)
    branch_code: str = "00000"
    rdo_code: str = Field(default="", max_length=5)
    address: str = Field(default="", max_length=1000)
    zip_code: str = Field(default="", max_length=10)
    taxpayer_type: Literal["individual", "corporation", "partnership"] = "corporation"
    vat_status: Literal["vat", "non_vat"] = "vat"
    income_tax_option: Literal["graduated", "eight_percent"] = "graduated"
    deduction_method: Literal["itemized", "osd"] = "itemized"
    business_type: Literal["trading", "manufacturing", "services"] = "trading"
    is_withholding_agent: bool = False
    is_top_withholding_agent: bool = False
    has_employees: bool = False
    fiscal_year_end_month: int = Field(default=12, ge=1, le=12)
    pinned: bool = False

    @field_validator("registered_name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Registered name is required")
        return v

    @field_validator("aliases")
    @classmethod
    def _clean_aliases(cls, v: list[str]) -> list[str]:
        return [a.strip()[:255] for a in v if a and a.strip()]

    @field_validator("tin")
    @classmethod
    def _tin(cls, v: str) -> str:
        return _tin_base(v)

    @field_validator("branch_code")
    @classmethod
    def _branch(cls, v: str) -> str:
        digits = re.sub(r"\D", "", v or "")[:5]
        return digits.zfill(5) if digits else "00000"

    @model_validator(mode="after")
    def _eight_percent_individuals_only(self):
        if self.income_tax_option == "eight_percent" and self.taxpayer_type != "individual":
            raise ValueError("The 8% income tax option is only for individuals")
        return self


class CompanyOut(CompanyIn):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime


class CompanyBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    registered_name: str
    tin: str


class UploadFileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    original_filename: str
    status: str
    company_id: uuid.UUID | None
    error_message: str | None


class UploadGroupOut(BaseModel):
    key: str
    company: CompanyBrief | None
    level: Literal["certain", "likely", "unknown"]
    detected_name: str
    detected_tin: str
    detected_address: str
    file_ids: list[uuid.UUID]
    file_names: list[str]


class UploadOut(BaseModel):
    id: uuid.UUID
    status: str
    total_files: int
    processed_files: int
    preselected_company_id: uuid.UUID | None
    files: list[UploadFileOut]
    groups: list[UploadGroupOut]


class ConfirmAssignment(BaseModel):
    file_ids: list[uuid.UUID] = Field(min_length=1)
    company_id: uuid.UUID | None = None
    skip: bool = False

    @model_validator(mode="after")
    def _one_target(self):
        if (self.company_id is None) == (not self.skip):
            raise ValueError("Each assignment needs either a company_id or skip=true")
        return self


class ConfirmIn(BaseModel):
    assignments: list[ConfirmAssignment] = Field(min_length=1)


class TreeQuarterOut(BaseModel):
    year: int
    quarter: int
    label: str
    document_count: int
    review_count: int


class TreeYearOut(BaseModel):
    year: int
    quarters: list[TreeQuarterOut]


class TreeCompanyOut(BaseModel):
    id: uuid.UUID
    registered_name: str
    tin: str
    pinned: bool
    fiscal_year_end_month: int
    years: list[TreeYearOut]
    undated_count: int


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    file_id: uuid.UUID
    page_start: int
    page_end: int
    document_title: str
    doc_type: str
    category: str
    account: str
    client_role: str
    doc_number: str
    doc_date: date | None
    period_year: int | None
    period_quarter: int | None
    period_month: int | None
    period_locked: bool
    seller_name: str
    seller_tin: str
    seller_address: str
    seller_vat_registered: bool | None
    buyer_name: str
    buyer_tin: str
    buyer_address: str
    gross_amount: Decimal
    vatable_amount: Decimal
    vat_amount: Decimal
    exempt_amount: Decimal
    zero_rated_amount: Decimal
    withholding_amount: Decimal
    vat_treatment: str
    input_vat_valid: bool | None
    confidence: float
    needs_review: bool
    review_reasons: list[str]
    reviewed: bool
    excluded: bool
    created_at: datetime


class FolderOut(BaseModel):
    company: CompanyBrief
    year: int | None
    quarter: int | None
    label: str
    counts: dict[str, int]
    documents: list[DocumentOut]


class DocumentPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: Category | None = None
    account: Account | None = None
    doc_number: str | None = Field(default=None, max_length=60)
    doc_date: date | None = None
    period_year: int | None = Field(default=None, ge=2000, le=2100)
    period_quarter: int | None = Field(default=None, ge=1, le=4)
    seller_name: str | None = Field(default=None, max_length=255)
    seller_tin: str | None = None
    buyer_name: str | None = Field(default=None, max_length=255)
    buyer_tin: str | None = None
    gross_amount: Decimal | None = _money_field()
    vatable_amount: Decimal | None = _money_field()
    vat_amount: Decimal | None = _money_field()
    exempt_amount: Decimal | None = _money_field()
    zero_rated_amount: Decimal | None = _money_field()
    withholding_amount: Decimal | None = _money_field()
    vat_treatment: VatTreatment | None = None
    reviewed: bool | None = None
    excluded: bool | None = None

    @field_validator("seller_tin", "buyer_tin")
    @classmethod
    def _tin(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return "" if v is not None else None
        return _tin_base(v)

    @model_validator(mode="after")
    def _period_pair(self):
        sent = self.model_fields_set
        if ("period_year" in sent) != ("period_quarter" in sent):
            raise ValueError("period_year and period_quarter must be sent together")
        if (self.period_year is None) != (self.period_quarter is None):
            raise ValueError("period_year and period_quarter must both be set or both be null")
        return self
```

`backend/app/services/accounting/storage.py`:

```python
"""Upload storage for AutoAccounting: stream files to the long-retention root."""

import hashlib
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile

from app.config import settings
from app.services.file_service import validate_file
from app.services.gemini_service import get_pdf_page_count_safe

ALLOWED_EXTS = {".pdf": "pdf", ".png": "png", ".jpg": "jpg", ".jpeg": "jpg"}
_CHUNK = 1024 * 1024


class UploadRejected(ValueError):
    """A file the user must be told about by name (bad type, empty, unreadable)."""


@dataclass(frozen=True)
class StoredUpload:
    filename: str
    stored_path: str
    size: int
    sha256: str
    file_type: str
    page_count: int


def upload_dir(upload_id: uuid.UUID) -> Path:
    return Path(settings.accounting_root) / "accounting" / str(upload_id)


async def stream_upload(f: UploadFile, dest_dir: Path) -> StoredUpload:
    """Write one upload under ``dest_dir``; validate type, size, magic bytes and readability."""
    filename = (f.filename or "unknown")[:255]
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTS:
        raise UploadRejected(f"'{filename}': only PDF, PNG and JPG files are accepted")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{uuid.uuid4()}{ext}"
    max_bytes = settings.max_file_size_mb * 1024 * 1024
    digest = hashlib.sha256()
    total = 0
    header = b""
    try:
        with open(dest, "wb") as out:
            while chunk := await f.read(_CHUNK):
                total += len(chunk)
                if total > max_bytes:
                    raise UploadRejected(f"'{filename}' exceeds the {settings.max_file_size_mb}MB limit")
                if len(header) < 16:
                    header += chunk[: 16 - len(header)]
                digest.update(chunk)
                out.write(chunk)
        if total == 0:
            raise UploadRejected(f"'{filename}' is empty")
        ok, err = validate_file(filename, total, header)
        if not ok:
            raise UploadRejected(f"'{filename}': {err}")
        file_type = ALLOWED_EXTS[ext]
        page_count = 1
        if file_type == "pdf":
            page_count = get_pdf_page_count_safe(str(dest))
            if page_count < 1:
                raise UploadRejected(f"'{filename}' couldn't be opened as a PDF")
    except UploadRejected:
        dest.unlink(missing_ok=True)
        raise
    return StoredUpload(filename, str(dest), total, digest.hexdigest(), file_type, page_count)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec -T backend python -m pytest tests/test_accounting_schemas.py tests/test_accounting_storage.py -v`
Expected: PASS (5 + 5 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/accounting.py backend/app/services/accounting/storage.py backend/tests/test_accounting_schemas.py backend/tests/test_accounting_storage.py
git commit -m "feat(accounting): API schemas and validated upload storage

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Background pipeline (detection + extraction)

**Files:**
- Create: `backend/app/services/accounting/pipeline.py`

**Interfaces:**
- Consumes: models (Task 5); `call_gemini_raw`, `pdf_chunks_for_gemini`, `render_pdf_page_jpeg` (Task 1 / existing); `DETECT_PROMPT`, `EXTRACT_PROMPT`, `parse_detection`, `parse_extraction` (Task 3); `match_company`, `CompanyCandidate`, `detection_json` (Task 4); `classify_document`, `CompanyProfile`, `empty_document_fields`, `mark_duplicate` (Task 4); `charge_for_pages`, `increment_usage`, `get_enterprise_for_user` (existing).
- Produces: `start_detection(upload_id: uuid.UUID, user_id: str) -> None`; `start_extraction(upload_id: uuid.UUID, user_id: str) -> None` (both schedule a background task and return immediately); `company_candidates(companies) -> list[CompanyCandidate]`; `company_profile(c: AACompany) -> CompanyProfile`.

This task is DB + Gemini bound; per project convention it is verified manually (Task 12), not unit-tested. The pure pieces it calls are covered by Tasks 2–6.

- [ ] **Step 1: Implement** — `backend/app/services/accounting/pipeline.py`:

```python
"""Background detection + extraction for AutoAccounting uploads.

Each job opens its own session (no request context), binds the uploader for
RLS parity with the rest of the app, and commits before every Gemini call so
no transaction is held open across the network (transaction pooler).
"""

import asyncio
import logging
import uuid
from pathlib import Path

from sqlalchemy import select

from app.database import async_session
from app.dependencies import bind_session_user
from app.models.accounting import AACompany, AADocument, AAFile, AASupplierRule, AAUpload
from app.models.user import User
from app.services import gemini_service
from app.services.accounting.classify import (
    CompanyProfile, classify_document, empty_document_fields, mark_duplicate,
)
from app.services.accounting.extraction import (
    DETECT_PROMPT, EXTRACT_PROMPT, parse_detection, parse_extraction,
)
from app.services.accounting.matching import CompanyCandidate, detection_json, match_company
from app.services.usage_service import charge_for_pages, get_enterprise_for_user, increment_usage

logger = logging.getLogger(__name__)

# Accounting jobs per instance; each holds a DB session for its run.
_JOB_SEM = asyncio.Semaphore(2)
_TASKS: set[asyncio.Task] = set()
_IMAGE_MIME = {"png": "image/png", "jpg": "image/jpeg"}


def company_candidates(companies) -> list[CompanyCandidate]:
    return [
        CompanyCandidate(str(c.id), c.registered_name, c.tin, tuple(c.aliases or ()))
        for c in companies
    ]


def company_profile(c: AACompany) -> CompanyProfile:
    return CompanyProfile(
        c.tin, c.registered_name, tuple(c.aliases or ()), c.vat_status == "vat", c.fiscal_year_end_month
    )


def _spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)


def start_detection(upload_id: uuid.UUID, user_id: str) -> None:
    _spawn(_guarded(run_detection, upload_id, user_id))


def start_extraction(upload_id: uuid.UUID, user_id: str) -> None:
    _spawn(_guarded(run_extraction, upload_id, user_id))


async def _guarded(job, upload_id: uuid.UUID, user_id: str) -> None:
    try:
        async with _JOB_SEM:
            await job(upload_id, user_id)
    except Exception:
        logger.exception("accounting_job_failed upload_id=%s", upload_id)
        async with async_session() as db:
            await bind_session_user(db, user_id)
            upload = await db.get(AAUpload, upload_id)
            if upload is not None:
                upload.status = "failed"
                await db.commit()


async def _first_page(stored_path: str, file_type: str) -> tuple[bytes, str]:
    loop = asyncio.get_running_loop()
    if file_type == "pdf":
        data = await loop.run_in_executor(None, gemini_service.render_pdf_page_jpeg, stored_path, 0)
        return data, "image/jpeg"
    data = await loop.run_in_executor(None, Path(stored_path).read_bytes)
    return data, _IMAGE_MIME[file_type]


async def _chunks(stored_path: str, file_type: str) -> list[tuple[bytes, str, int, int]]:
    """(bytes, mime, start_page_0, end_page_0) pieces to send to Gemini."""
    loop = asyncio.get_running_loop()
    if file_type == "pdf":
        chunks = await loop.run_in_executor(None, gemini_service.pdf_chunks_for_gemini, stored_path)
        return [(b, "application/pdf", s, e) for b, s, e in chunks]
    data = await loop.run_in_executor(None, Path(stored_path).read_bytes)
    return [(data, _IMAGE_MIME[file_type], 0, 0)]


async def run_detection(upload_id: uuid.UUID, user_id: str) -> None:
    async with async_session() as db:
        await bind_session_user(db, user_id)
        upload = await db.get(AAUpload, upload_id)
        if upload is None:
            return
        companies = (await db.execute(
            select(AACompany).where(AACompany.enterprise_id == upload.enterprise_id)
        )).scalars().all()
        candidates = company_candidates(companies)
        files = (await db.execute(
            select(AAFile)
            .where(AAFile.upload_id == upload_id, AAFile.status == "uploaded")
            .order_by(AAFile.created_at)
        )).scalars().all()
        jobs = [(f.id, f.stored_path, f.file_type) for f in files]
        await db.commit()

        for file_id, stored_path, file_type in jobs:
            try:
                image, mime = await _first_page(stored_path, file_type)
                raw = await gemini_service.call_gemini_raw(image, mime, DETECT_PROMPT, user_id)
                detection = parse_detection(raw)
                result = detection_json(detection, match_company(detection.seller, detection.buyer, candidates))
            except Exception as e:  # one bad file never blocks the rest
                logger.warning("accounting_detect_failed file_id=%s error=%s", file_id, str(e)[:200])
                result = {"error": str(e)[:200]}
            f = await db.get(AAFile, file_id)
            f.detection = result
            f.status = "detected"
            upload = await db.get(AAUpload, upload_id)
            upload.processed_files += 1
            await db.commit()

        upload = await db.get(AAUpload, upload_id)
        upload.status = "awaiting_confirmation"
        await db.commit()


async def run_extraction(upload_id: uuid.UUID, user_id: str) -> None:
    async with async_session() as db:
        await bind_session_user(db, user_id)
        upload = await db.get(AAUpload, upload_id)
        if upload is None:
            return
        enterprise_scope = upload.enterprise_id
        uploader = await db.get(User, upload.uploaded_by)
        enterprise = await get_enterprise_for_user(db, uploader) if uploader else None
        enterprise_id = enterprise.id if enterprise else None

        files = (await db.execute(
            select(AAFile)
            .where(
                AAFile.upload_id == upload_id,
                AAFile.company_id.is_not(None),
                AAFile.status.in_(("uploaded", "detected")),
            )
            .order_by(AAFile.created_at)
        )).scalars().all()
        jobs = [(f.id, f.company_id, f.stored_path, f.file_type, f.page_count) for f in files]
        company_ids = list({company_id for _, company_id, *_ in jobs})

        companies = (await db.execute(
            select(AACompany).where(AACompany.id.in_(company_ids))
        )).scalars().all() if company_ids else []
        profiles = {c.id: company_profile(c) for c in companies}
        all_tins = (await db.execute(
            select(AACompany.id, AACompany.tin)
            .where(AACompany.enterprise_id == enterprise_scope, AACompany.tin != "")
        )).all()
        rules: dict[uuid.UUID, dict[str, tuple[str, str]]] = {}
        for r in (await db.execute(
            select(AASupplierRule).where(AASupplierRule.company_id.in_(company_ids))
        )).scalars().all() if company_ids else []:
            rules.setdefault(r.company_id, {})[r.counterparty_tin] = (r.category, r.account)
        seen: dict[uuid.UUID, set[tuple[str, str]]] = {cid: set() for cid in company_ids}
        for company_id, seller_tin, doc_number in (await db.execute(
            select(AADocument.company_id, AADocument.seller_tin, AADocument.doc_number)
            .where(
                AADocument.company_id.in_(company_ids),
                AADocument.doc_number != "",
                AADocument.deleted_at.is_(None),
            )
        )).all() if company_ids else []:
            seen[company_id].add((seller_tin, doc_number.strip().upper()))

        upload.status = "extracting"
        upload.total_files = len(jobs)
        upload.processed_files = 0
        for f in files:
            f.status = "extracting"
        await db.commit()

        for file_id, company_id, stored_path, file_type, page_count in jobs:
            profile = profiles.get(company_id)
            others = frozenset(t for cid, t in all_tins if cid != company_id)
            try:
                if profile is None:
                    raise ValueError("company no longer exists")
                extracted = []
                for data, mime, start0, end0 in await _chunks(stored_path, file_type):
                    raw = await gemini_service.call_gemini_raw(data, mime, EXTRACT_PROMPT, user_id)
                    extracted += parse_extraction(raw, page_offset=start0, chunk_pages=end0 - start0 + 1)

                rows = [classify_document(ext, profile, rules.get(company_id, {}), others) for ext in extracted]
                if not rows:
                    rows = [empty_document_fields(page_count)]
                for fields in rows:
                    mark_duplicate(fields, seen[company_id])
                    db.add(AADocument(
                        enterprise_id=enterprise_scope, company_id=company_id, file_id=file_id, **fields
                    ))

                f = await db.get(AAFile, file_id)
                if not f.pages_charged and enterprise_id is not None:
                    ent = await db.get(User, enterprise_id)
                    await charge_for_pages(db, ent, page_count)
                    await increment_usage(db, enterprise_id, page_count)
                    f.pages_charged = True
                f.status = "extracted"
                f.error_message = None
            except Exception as e:  # file-level isolation, like the 2307 pipeline
                logger.exception("accounting_extract_failed file_id=%s", file_id)
                await db.rollback()
                f = await db.get(AAFile, file_id)
                f.status = "error"
                f.error_message = str(e)[:500]
            upload = await db.get(AAUpload, upload_id)
            upload.processed_files += 1
            await db.commit()

        upload = await db.get(AAUpload, upload_id)
        upload.status = "done"
        await db.commit()
```

- [ ] **Step 2: Static check**

Run: `docker compose exec -T backend python -c "import app.services.accounting.pipeline as p; print(p.start_detection, p.start_extraction)"`
Expected: prints two function objects, no ImportError.
Run: `docker compose exec -T backend python -m pytest -q`
Expected: whole suite passes.

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/accounting/pipeline.py
git commit -m "feat(accounting): background detection and extraction pipeline

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Router — companies, uploads, confirmation

**Files:**
- Create: `backend/app/routers/accounting.py`
- Modify: `backend/app/main.py` (router import line 21 and `include_router` block ~line 437)

**Interfaces:**
- Consumes: Tasks 4–7.
- Produces HTTP (all under `/api/accounting`, gated by `require_feature("accounting")`):
  - `GET /companies?q=` → `list[CompanyOut]`
  - `POST /companies` (manager+) → `CompanyOut` 201; 409 on duplicate TIN+branch
  - `PUT /companies/{company_id}` (manager+) → `CompanyOut`
  - `POST /uploads` multipart `files[]`, optional form `company_id` → `UploadOut` 201
  - `GET /uploads/{upload_id}` → `UploadOut`
  - `POST /uploads/{upload_id}/confirm` body `ConfirmIn` → `UploadOut`; 409 if not awaiting confirmation
- Produces (module helpers reused in Task 9): `_scope(user) -> uuid.UUID`, `_company_or_404(db, ent, company_id) -> AACompany`.

- [ ] **Step 1: Implement** — `backend/app/routers/accounting.py`:

```python
"""AutoAccounting phase 1: company databank, uploads, folder tree, documents."""

import re
import shutil
import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import upload_limiter
from app.config import settings
from app.dependencies import get_current_user, get_db
from app.models.accounting import AACompany, AAFile, AAUpload
from app.models.user import User, UserRole
from app.schemas.accounting import (
    CompanyBrief, CompanyIn, CompanyOut, ConfirmIn, UploadFileOut, UploadGroupOut, UploadOut,
)
from app.services.accounting import pipeline
from app.services.accounting.matching import file_detection_from_json, suggest_groups
from app.services.accounting.storage import UploadRejected, stream_upload, upload_dir
from app.services.usage_service import get_enterprise_for_user

router = APIRouter()

_MANAGER_ROLES = (UserRole.ADMIN, UserRole.ENTERPRISE, UserRole.MANAGER)
_MEMBER_ROLES = _MANAGER_ROLES + (UserRole.EMPLOYEE,)


def _scope(user: User) -> uuid.UUID:
    """The firm (enterprise owner id) every AutoAccounting row is scoped to."""
    if user.role not in _MEMBER_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Your account cannot use AutoAccounting")
    if user.role in (UserRole.ADMIN, UserRole.ENTERPRISE):
        return user.id
    if user.enterprise_id is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Your account is not part of a firm")
    return user.enterprise_id


def _require_manager(user: User) -> None:
    if user.role not in _MANAGER_ROLES:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only owners and managers can change the company databank"
        )


async def _company_or_404(db: AsyncSession, ent: uuid.UUID, company_id: uuid.UUID) -> AACompany:
    company = (await db.execute(
        select(AACompany).where(AACompany.id == company_id, AACompany.enterprise_id == ent)
    )).scalar_one_or_none()
    if company is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Company not found")
    return company


async def _assert_budget(db: AsyncSession, user: User) -> None:
    if user.role == UserRole.ADMIN:
        return
    enterprise = await get_enterprise_for_user(db, user)
    if enterprise is not None and (enterprise.budget or 0) <= 0:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Budget depleted. Contact your administrator to top up before uploading again.",
        )


# --- Companies -----------------------------------------------------------------

@router.get("/companies", response_model=list[CompanyOut])
async def list_companies(
    q: str = Query(default="", max_length=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ent = _scope(user)
    stmt = select(AACompany).where(AACompany.enterprise_id == ent)
    term = q.strip()
    if term:
        conds = [AACompany.registered_name.ilike(f"%{term}%")]
        digits = re.sub(r"\D", "", term)
        if digits:
            conds.append(AACompany.tin.like(f"{digits}%"))
        stmt = stmt.where(or_(*conds))
    stmt = stmt.order_by(AACompany.pinned.desc(), AACompany.registered_name).limit(500)
    return (await db.execute(stmt)).scalars().all()


@router.post("/companies", response_model=CompanyOut, status_code=status.HTTP_201_CREATED)
async def create_company(
    body: CompanyIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    ent = _scope(user)
    _require_manager(user)
    company = AACompany(enterprise_id=ent, created_by=user.id, **body.model_dump())
    db.add(company)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "A company with this TIN and branch code is already in your databank"
        )
    return company


@router.put("/companies/{company_id}", response_model=CompanyOut)
async def update_company(
    company_id: uuid.UUID,
    body: CompanyIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ent = _scope(user)
    _require_manager(user)
    company = await _company_or_404(db, ent, company_id)
    for name, value in body.model_dump().items():
        setattr(company, name, value)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "A company with this TIN and branch code is already in your databank"
        )
    return company


# --- Uploads -------------------------------------------------------------------

async def _upload_out(db: AsyncSession, ent: uuid.UUID, upload_id: uuid.UUID) -> UploadOut:
    upload = (await db.execute(
        select(AAUpload).where(AAUpload.id == upload_id, AAUpload.enterprise_id == ent)
    )).scalar_one_or_none()
    if upload is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Upload not found")
    files = (await db.execute(
        select(AAFile).where(AAFile.upload_id == upload_id).order_by(AAFile.created_at)
    )).scalars().all()

    groups: list[UploadGroupOut] = []
    if upload.status == "awaiting_confirmation":
        detected = [f for f in files if f.status == "detected"]
        raw_groups = suggest_groups([file_detection_from_json(str(f.id), f.detection or {}) for f in detected])
        ids = {uuid.UUID(g.company_id) for g in raw_groups if g.company_id}
        companies = {
            str(c.id): c
            for c in (await db.execute(
                select(AACompany).where(AACompany.id.in_(list(ids)), AACompany.enterprise_id == ent)
            )).scalars().all()
        } if ids else {}
        names = {str(f.id): f.original_filename for f in files}
        for g in raw_groups:
            company = companies.get(g.company_id) if g.company_id else None
            groups.append(UploadGroupOut(
                key=g.key,
                company=CompanyBrief.model_validate(company) if company else None,
                level=g.level if company else "unknown",
                detected_name=g.detected.name,
                detected_tin=g.detected.tin,
                detected_address=g.detected.address,
                file_ids=[uuid.UUID(fid) for fid in g.file_ids],
                file_names=[names[fid] for fid in g.file_ids],
            ))
    return UploadOut(
        id=upload.id,
        status=upload.status,
        total_files=upload.total_files,
        processed_files=upload.processed_files,
        preselected_company_id=upload.preselected_company_id,
        files=[UploadFileOut.model_validate(f) for f in files],
        groups=groups,
    )


@router.post("/uploads", response_model=UploadOut, status_code=status.HTTP_201_CREATED)
async def create_upload(
    files: list[UploadFile],
    company_id: uuid.UUID | None = Form(default=None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ent = _scope(user)
    if settings.environment == "production" and not settings.accounting_dir:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "AutoAccounting storage is not configured yet")
    if not upload_limiter.check_and_record(str(user.id)):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "Too many uploads. Please try again later.",
            headers={"Retry-After": "60"},
        )
    await _assert_budget(db, user)
    if not files:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No files were uploaded")
    if len(files) > settings.max_batch_size:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Upload exceeds the maximum of {settings.max_batch_size} files")
    company = await _company_or_404(db, ent, company_id) if company_id else None

    upload_id = uuid.uuid4()
    dest = upload_dir(upload_id)
    stored = []
    try:
        for f in files:
            stored.append(await stream_upload(f, dest))
    except UploadRejected as e:
        shutil.rmtree(dest, ignore_errors=True)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))

    known = set((await db.execute(
        select(AAFile.sha256).where(
            AAFile.enterprise_id == ent,
            AAFile.sha256.in_(list({s.sha256 for s in stored})),
            AAFile.status.not_in(("skipped", "error")),
        )
    )).scalars())
    db.add(AAUpload(
        id=upload_id, enterprise_id=ent, uploaded_by=user.id,
        preselected_company_id=company.id if company else None,
        status="extracting" if company else "detecting",
    ))
    await db.flush()
    fresh = 0
    for s in stored:
        duplicate = s.sha256 in known
        known.add(s.sha256)
        fresh += 0 if duplicate else 1
        db.add(AAFile(
            enterprise_id=ent, upload_id=upload_id,
            company_id=company.id if company and not duplicate else None,
            original_filename=s.filename, stored_path=s.stored_path, file_type=s.file_type,
            file_size=s.size, sha256=s.sha256, page_count=s.page_count,
            status="duplicate" if duplicate else "uploaded",
        ))
    upload = await db.get(AAUpload, upload_id)
    upload.total_files = fresh
    if fresh == 0:
        upload.status = "done"
    await db.commit()

    if fresh:
        if company:
            pipeline.start_extraction(upload_id, str(user.id))
        else:
            pipeline.start_detection(upload_id, str(user.id))
    return await _upload_out(db, ent, upload_id)


@router.get("/uploads/{upload_id}", response_model=UploadOut)
async def get_upload(
    upload_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    return await _upload_out(db, _scope(user), upload_id)


@router.post("/uploads/{upload_id}/confirm", response_model=UploadOut)
async def confirm_upload(
    upload_id: uuid.UUID,
    body: ConfirmIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ent = _scope(user)
    # Claim the upload atomically so a double-click can't start two extractions.
    claimed = await db.execute(
        update(AAUpload)
        .where(AAUpload.id == upload_id, AAUpload.enterprise_id == ent,
               AAUpload.status == "awaiting_confirmation")
        .values(status="confirming")
    )
    if claimed.rowcount != 1:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "This upload is not waiting for confirmation")

    files = {f.id: f for f in (await db.execute(
        select(AAFile).where(AAFile.upload_id == upload_id, AAFile.status == "detected")
    )).scalars().all()}
    company_ids = {a.company_id for a in body.assignments if a.company_id}
    valid = set((await db.execute(
        select(AACompany.id).where(AACompany.id.in_(list(company_ids)), AACompany.enterprise_id == ent)
    )).scalars()) if company_ids else set()
    if company_ids - valid:
        await db.rollback()
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Company not found")

    assigned: set[uuid.UUID] = set()
    for a in body.assignments:
        for fid in a.file_ids:
            if fid not in files or fid in assigned:
                await db.rollback()
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown or repeated file in assignments")
            assigned.add(fid)
            if a.skip:
                files[fid].status = "skipped"
            else:
                files[fid].company_id = a.company_id
    if assigned != set(files):
        await db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Every file must be assigned to a company or skipped")

    has_work = any(not a.skip for a in body.assignments)
    upload = await db.get(AAUpload, upload_id)
    upload.status = "extracting" if has_work else "done"
    await db.commit()
    if has_work:
        pipeline.start_extraction(upload_id, str(user.id))
    return await _upload_out(db, ent, upload_id)
```

`backend/app/main.py` — extend the router import on line 21 with `accounting`, and add after the invoices `include_router` block:

```python
app.include_router(
    accounting.router,
    prefix="/api/accounting",
    tags=["accounting"],
    dependencies=[Depends(require_feature("accounting"))],
)
```

- [ ] **Step 2: Verify the app loads and routes are mounted**

Run: `docker compose restart backend && sleep 8 && docker compose logs --tail=20 backend`
Expected: no traceback.
Run: `curl -s -A "dev-check" http://localhost:8000/openapi.json | python3 -c "import json,sys; print(sorted(p for p in json.load(sys.stdin)['paths'] if 'accounting' in p))"`
Expected: `['/api/accounting/companies', '/api/accounting/companies/{company_id}', '/api/accounting/uploads', '/api/accounting/uploads/{upload_id}', '/api/accounting/uploads/{upload_id}/confirm']`.

- [ ] **Step 3: Run the suite**

Run: `docker compose exec -T backend python -m pytest -q`
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add backend/app/routers/accounting.py backend/app/main.py
git commit -m "feat(accounting): companies, uploads and confirmation endpoints

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Router — tree, folders, documents, page images

**Files:**
- Modify: `backend/app/routers/accounting.py` (append)

**Interfaces:**
- Consumes: `build_tree`, `folder_counts`, `TreeCompanyInput` (Task 5); `period_for`, `quarter_label` (Task 2); `DocumentOut`, `DocumentPatch`, `FolderOut`, `TreeCompanyOut` (Task 6); `_scope`, `_company_or_404` (Task 8).
- Produces HTTP:
  - `GET /tree` → `list[TreeCompanyOut]` (every company, even with no documents)
  - `GET /folders?company_id=&year=&quarter=` → `FolderOut` (omit year+quarter for *Undated*)
  - `GET /documents/{doc_id}` → `DocumentOut`
  - `PATCH /documents/{doc_id}` body `DocumentPatch` → `DocumentOut` (learns supplier rules on category/account change)
  - `DELETE /documents/{doc_id}` → 204 (soft delete)
  - `GET /files/{file_id}/pages/{page}` → `image/webp` (PDF) or the original PNG/JPEG

- [ ] **Step 1: Implement** — add these imports to the top of `backend/app/routers/accounting.py` (merge into the existing `fastapi`, `sqlalchemy`, `app.models.accounting` and `app.schemas.accounting` import lines rather than duplicating them):

```python
import asyncio
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Path as PathParam
from fastapi.responses import Response
from sqlalchemy import case, func

from app.models.accounting import AADocument, AASupplierRule
from app.schemas.accounting import DocumentOut, DocumentPatch, FolderOut, TreeCompanyOut
from app.services import gemini_service
from app.services.accounting.periods import period_for, quarter_label
from app.services.accounting.tree import TreeCompanyInput, build_tree, folder_counts
from app.services.file_service import validate_stored_path
```

…and append:

```python
# --- Tree, folders, documents --------------------------------------------------

_IMAGE_MIME = {"png": "image/png", "jpg": "image/jpeg"}
_PLAIN_FIELDS = (
    "category", "account", "doc_number", "doc_date", "seller_name", "seller_tin", "buyer_name",
    "buyer_tin", "gross_amount", "vatable_amount", "vat_amount", "exempt_amount",
    "zero_rated_amount", "withholding_amount", "vat_treatment", "reviewed", "excluded",
)
_NULLABLE_FIELDS = {"doc_date"}


@router.get("/tree", response_model=list[TreeCompanyOut])
async def get_tree(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    ent = _scope(user)
    companies = (await db.execute(
        select(AACompany).where(AACompany.enterprise_id == ent)
        .order_by(AACompany.pinned.desc(), AACompany.registered_name)
    )).scalars().all()
    open_review = case(
        (AADocument.needs_review & ~AADocument.reviewed & ~AADocument.excluded, 1), else_=0
    )
    rows = (await db.execute(
        select(
            AADocument.company_id, AADocument.period_year, AADocument.period_quarter,
            func.count(), func.sum(open_review),
        )
        .where(AADocument.enterprise_id == ent, AADocument.deleted_at.is_(None))
        .group_by(AADocument.company_id, AADocument.period_year, AADocument.period_quarter)
    )).all()
    inputs = [
        TreeCompanyInput(str(c.id), c.registered_name, c.tin, c.pinned, c.fiscal_year_end_month)
        for c in companies
    ]
    return build_tree(inputs, [tuple(r) for r in rows])


@router.get("/folders", response_model=FolderOut)
async def get_folder(
    company_id: uuid.UUID,
    year: int | None = Query(default=None, ge=2000, le=2100),
    quarter: int | None = Query(default=None, ge=1, le=4),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ent = _scope(user)
    company = await _company_or_404(db, ent, company_id)
    if (year is None) != (quarter is None):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Pass both year and quarter, or neither for undated")
    stmt = select(AADocument).where(AADocument.company_id == company.id, AADocument.deleted_at.is_(None))
    if year is None:
        stmt = stmt.where(AADocument.period_year.is_(None))
        label = "Undated"
    else:
        stmt = stmt.where(AADocument.period_year == year, AADocument.period_quarter == quarter)
        label = f"{year} · {quarter_label(quarter, company.fiscal_year_end_month)}"
    docs = (await db.execute(
        stmt.order_by(AADocument.doc_date.asc().nulls_last(), AADocument.created_at)
    )).scalars().all()
    return FolderOut(
        company=CompanyBrief.model_validate(company),
        year=year,
        quarter=quarter,
        label=label,
        counts=folder_counts([(d.category, d.needs_review, d.reviewed, d.excluded) for d in docs]),
        documents=[DocumentOut.model_validate(d) for d in docs],
    )


async def _document_or_404(db: AsyncSession, ent: uuid.UUID, doc_id: uuid.UUID) -> AADocument:
    doc = (await db.execute(
        select(AADocument).where(
            AADocument.id == doc_id, AADocument.enterprise_id == ent, AADocument.deleted_at.is_(None)
        )
    )).scalar_one_or_none()
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return doc


def _apply_period_from_date(doc: AADocument, company: AACompany) -> None:
    if doc.doc_date is None:
        doc.period_year = doc.period_quarter = doc.period_month = None
        return
    p = period_for(doc.doc_date, company.fiscal_year_end_month)
    doc.period_year, doc.period_quarter, doc.period_month = p.fiscal_year, p.quarter, p.month_in_quarter


async def _learn_supplier_rule(db: AsyncSession, doc: AADocument) -> None:
    tin = doc.buyer_tin if doc.client_role == "seller" else doc.seller_tin
    if not tin or doc.category not in ("purchases", "expenses"):
        return
    rule = (await db.execute(
        select(AASupplierRule).where(
            AASupplierRule.company_id == doc.company_id, AASupplierRule.counterparty_tin == tin
        )
    )).scalar_one_or_none()
    if rule is None:
        db.add(AASupplierRule(company_id=doc.company_id, counterparty_tin=tin,
                              category=doc.category, account=doc.account))
    else:
        rule.category, rule.account = doc.category, doc.account


@router.get("/documents/{doc_id}", response_model=DocumentOut)
async def get_document(
    doc_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    return await _document_or_404(db, _scope(user), doc_id)


@router.patch("/documents/{doc_id}", response_model=DocumentOut)
async def patch_document(
    doc_id: uuid.UUID,
    body: DocumentPatch,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ent = _scope(user)
    doc = await _document_or_404(db, ent, doc_id)
    company = await _company_or_404(db, ent, doc.company_id)
    sent = body.model_fields_set

    for name in _PLAIN_FIELDS:
        if name not in sent:
            continue
        value = getattr(body, name)
        if value is None and name not in _NULLABLE_FIELDS:
            continue
        setattr(doc, name, value)

    if "period_year" in sent:
        if body.period_year is None:
            doc.period_locked = False
            _apply_period_from_date(doc, company)
        else:
            doc.period_year, doc.period_quarter, doc.period_month = body.period_year, body.period_quarter, None
            doc.period_locked = True
    elif "doc_date" in sent and not doc.period_locked:
        _apply_period_from_date(doc, company)

    if sent & {"category", "account"}:
        await _learn_supplier_rule(db, doc)

    await db.commit()
    return doc


@router.delete("/documents/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    doc_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    doc = await _document_or_404(db, _scope(user), doc_id)
    doc.deleted_at = datetime.now(timezone.utc)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/files/{file_id}/pages/{page}")
async def file_page(
    file_id: uuid.UUID,
    page: int = PathParam(ge=1, le=10000),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ent = _scope(user)
    f = (await db.execute(
        select(AAFile).where(AAFile.id == file_id, AAFile.enterprise_id == ent)
    )).scalar_one_or_none()
    if f is None or page > f.page_count:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Page not found")
    try:
        validate_stored_path(f.stored_path)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Page not found")
    headers = {"Cache-Control": "private, max-age=3600"}
    loop = asyncio.get_running_loop()
    if f.file_type == "pdf":
        data = await loop.run_in_executor(None, gemini_service.render_pdf_page_webp, f.stored_path, page - 1)
        return Response(content=data, media_type="image/webp", headers=headers)
    data = await loop.run_in_executor(None, Path(f.stored_path).read_bytes)
    return Response(content=data, media_type=_IMAGE_MIME[f.file_type], headers=headers)
```

- [ ] **Step 2: Verify**

Run: `docker compose restart backend && sleep 8 && docker compose logs --tail=20 backend`
Expected: no traceback.
Run: `curl -s -A "dev-check" http://localhost:8000/openapi.json | python3 -c "import json,sys; print(len([p for p in json.load(sys.stdin)['paths'] if 'accounting' in p]))"`
Expected: `10`.
Run: `docker compose exec -T backend python -m pytest -q`
Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add backend/app/routers/accounting.py
git commit -m "feat(accounting): tree, folder, document and page-image endpoints

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Frontend wiring — types, API client, route + nav + feature key

**Files:**
- Create: `frontend/src/types/accounting.ts`, `frontend/src/lib/accounting-format.ts`
- Modify: `frontend/src/lib/api.ts`, `frontend/src/types/index.ts:406-416`, `frontend/src/app/providers.tsx`, `frontend/src/components/layout/Sidebar.tsx`, `frontend/src/components/enterprise/feature-meta.ts`, `frontend/src/components/owner/feature-tabs.ts`

**Interfaces:**
- Produces: TS types `Company`, `CompanyInput`, `CompanyBrief`, `AAUploadFile`, `UploadGroup`, `Upload`, `ConfirmAssignment`, `TreeQuarter`, `TreeYear`, `TreeCompany`, `Category`, `AADocument`, `Folder`, `FolderRef`, `DocumentPatch`; `accountingApi` methods listed below; helpers `CATEGORY_LABELS`, `ACCOUNT_LABELS`, `ACCOUNTS`, `REASON_LABELS`, `formatTin`, `formatPeso`, `counterpartyName`, `apiErrorMessage`.

- [ ] **Step 1: Create `frontend/src/types/accounting.ts`**

```ts
export type TaxpayerType = "individual" | "corporation" | "partnership";

export interface CompanyInput {
  registered_name: string;
  aliases: string[];
  tin: string;
  branch_code: string;
  rdo_code: string;
  address: string;
  zip_code: string;
  taxpayer_type: TaxpayerType;
  vat_status: "vat" | "non_vat";
  income_tax_option: "graduated" | "eight_percent";
  deduction_method: "itemized" | "osd";
  business_type: "trading" | "manufacturing" | "services";
  is_withholding_agent: boolean;
  is_top_withholding_agent: boolean;
  has_employees: boolean;
  fiscal_year_end_month: number;
  pinned: boolean;
}

export interface Company extends CompanyInput {
  id: string;
  created_at: string;
}

export interface CompanyBrief {
  id: string;
  registered_name: string;
  tin: string;
}

export type UploadStatus =
  | "detecting"
  | "awaiting_confirmation"
  | "confirming"
  | "extracting"
  | "done"
  | "failed";

export interface AAUploadFile {
  id: string;
  original_filename: string;
  status: string;
  company_id: string | null;
  error_message: string | null;
}

export interface UploadGroup {
  key: string;
  company: CompanyBrief | null;
  level: "certain" | "likely" | "unknown";
  detected_name: string;
  detected_tin: string;
  detected_address: string;
  file_ids: string[];
  file_names: string[];
}

export interface Upload {
  id: string;
  status: UploadStatus;
  total_files: number;
  processed_files: number;
  preselected_company_id: string | null;
  files: AAUploadFile[];
  groups: UploadGroup[];
}

export interface ConfirmAssignment {
  file_ids: string[];
  company_id?: string;
  skip?: boolean;
}

export interface TreeQuarter {
  year: number;
  quarter: number;
  label: string;
  document_count: number;
  review_count: number;
}

export interface TreeYear {
  year: number;
  quarters: TreeQuarter[];
}

export interface TreeCompany {
  id: string;
  registered_name: string;
  tin: string;
  pinned: boolean;
  fiscal_year_end_month: number;
  years: TreeYear[];
  undated_count: number;
}

export type Category = "sales" | "purchases" | "expenses" | "payroll" | "2307" | "unsorted";

export interface AADocument {
  id: string;
  company_id: string;
  file_id: string;
  page_start: number;
  page_end: number;
  document_title: string;
  doc_type: string;
  category: Category;
  account: string;
  client_role: "seller" | "buyer";
  doc_number: string;
  doc_date: string | null;
  period_year: number | null;
  period_quarter: number | null;
  period_month: number | null;
  period_locked: boolean;
  seller_name: string;
  seller_tin: string;
  seller_address: string;
  seller_vat_registered: boolean | null;
  buyer_name: string;
  buyer_tin: string;
  buyer_address: string;
  gross_amount: string;
  vatable_amount: string;
  vat_amount: string;
  exempt_amount: string;
  zero_rated_amount: string;
  withholding_amount: string;
  vat_treatment: string;
  input_vat_valid: boolean | null;
  confidence: number;
  needs_review: boolean;
  review_reasons: string[];
  reviewed: boolean;
  excluded: boolean;
  created_at: string;
}

export interface Folder {
  company: CompanyBrief;
  year: number | null;
  quarter: number | null;
  label: string;
  counts: Record<string, number>;
  documents: AADocument[];
}

/** A quarter folder, or a company's Undated folder (year and quarter null). */
export interface FolderRef {
  companyId: string;
  year: number | null;
  quarter: number | null;
}

export type DocumentPatch = Record<string, string | number | boolean | null>;
```

- [ ] **Step 2: Create `frontend/src/lib/accounting-format.ts`**

```ts
import type { AxiosError } from "axios";
import type { AADocument } from "@/types/accounting";

export const CATEGORY_LABELS: Record<string, string> = {
  sales: "Sales",
  purchases: "Purchases",
  expenses: "Expenses",
  payroll: "Payroll",
  "2307": "2307s",
  unsorted: "Unsorted",
  review: "Review queue",
};

export const ACCOUNT_LABELS: Record<string, string> = {
  sales: "Sales",
  purchases: "Purchases (goods for resale)",
  raw_materials: "Raw materials",
  importation: "Importation",
  capital_goods: "Capital goods",
  salaries: "Salaries and wages",
  rent: "Rent",
  utilities: "Utilities",
  professional_fees: "Professional fees",
  office_supplies: "Office supplies",
  representation: "Representation / entertainment",
  transportation: "Transportation",
  repairs: "Repairs and maintenance",
  taxes_licenses: "Taxes and licenses",
  "2307_received": "2307 received",
  "2307_issued": "2307 issued",
  other: "Other",
};

export const ACCOUNTS = Object.keys(ACCOUNT_LABELS);

export const REASON_LABELS: Record<string, string> = {
  low_confidence: "Low extraction confidence. Check the amounts and date.",
  missing_date: "No readable date, so it can't be filed in a quarter.",
  missing_amount: "No total amount was found.",
  unsorted: "Couldn't tell what kind of document this is.",
  not_addressed_to_client: "Not addressed to the company's name or TIN, so no input VAT.",
  seller_not_vat_registered: "Seller isn't shown as VAT-registered, so no input VAT.",
  not_an_invoice: "Not an invoice. Receipts don't support input VAT.",
  vat_math_mismatch: "VAT isn't 12% of the VATable amount.",
  possible_duplicate: "Possible duplicate of a document already filed.",
  other_company_tin: "Shows another company's TIN from your databank.",
  nothing_extracted: "Nothing could be read from this file.",
};

export function formatTin(tin: string): string {
  const d = (tin || "").replace(/\D/g, "");
  return d.length >= 9 ? `${d.slice(0, 3)}-${d.slice(3, 6)}-${d.slice(6, 9)}` : d;
}

export function formatPeso(value: string | number): string {
  const n = Number(value);
  return Number.isFinite(n)
    ? n.toLocaleString("en-PH", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : "0.00";
}

export function counterpartyName(doc: AADocument): string {
  return doc.client_role === "seller" ? doc.buyer_name : doc.seller_name;
}

export function apiErrorMessage(e: unknown, fallback = "Something went wrong"): string {
  const detail = (e as AxiosError<{ detail?: unknown }>)?.response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length) {
    const first = detail[0] as { msg?: string };
    if (first?.msg) return first.msg.replace(/^Value error, /, "");
  }
  return fallback;
}
```

- [ ] **Step 3: Add `accountingApi` to `frontend/src/lib/api.ts`** — add an import below the existing `import type {…} from "@/types"` block:

```ts
import type {
  AADocument,
  Company,
  CompanyInput,
  ConfirmAssignment,
  DocumentPatch,
  Folder,
  TreeCompany,
  Upload,
} from "@/types/accounting";
```

…and append at the end of the file:

```ts
export const accountingApi = {
  listCompanies: (q = "") =>
    api.get<Company[]>("/accounting/companies", { params: q ? { q } : {} }).then((r) => r.data),
  createCompany: (data: CompanyInput) =>
    api.post<Company>("/accounting/companies", data).then((r) => r.data),
  updateCompany: (id: string, data: CompanyInput) =>
    api.put<Company>(`/accounting/companies/${id}`, data).then((r) => r.data),
  upload: (files: File[], companyId?: string) => {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    if (companyId) fd.append("company_id", companyId);
    return api
      .post<Upload>("/accounting/uploads", fd, { headers: { "Content-Type": "multipart/form-data" } })
      .then((r) => r.data);
  },
  getUpload: (id: string) => api.get<Upload>(`/accounting/uploads/${id}`).then((r) => r.data),
  confirmUpload: (id: string, assignments: ConfirmAssignment[]) =>
    api.post<Upload>(`/accounting/uploads/${id}/confirm`, { assignments }).then((r) => r.data),
  tree: () => api.get<TreeCompany[]>("/accounting/tree").then((r) => r.data),
  folder: (companyId: string, year: number | null, quarter: number | null) =>
    api
      .get<Folder>("/accounting/folders", {
        params: year != null && quarter != null
          ? { company_id: companyId, year, quarter }
          : { company_id: companyId },
      })
      .then((r) => r.data),
  updateDocument: (id: string, patch: DocumentPatch) =>
    api.patch<AADocument>(`/accounting/documents/${id}`, patch).then((r) => r.data),
  deleteDocument: (id: string) => api.delete(`/accounting/documents/${id}`).then(() => undefined),
  pageImage: (fileId: string, page: number) =>
    api
      .get<Blob>(`/accounting/files/${fileId}/pages/${page}`, { responseType: "blob" })
      .then((r) => r.data),
};
```

- [ ] **Step 4: Register the feature key and route**

`frontend/src/types/index.ts` — extend the union:

```ts
  | "invoices"
  | "accounting";
```

`frontend/src/app/providers.tsx` — in `canAccess`, add `pathname.startsWith("/accounting") ||` as the first line of the returned `||` chain for `admin`, for `enterprise`/`manager`, and for `employee`. In `FEATURE_PATHS` add:

```ts
  { prefix: "/accounting", key: "accounting" },
```

`frontend/src/components/layout/Sidebar.tsx` — add `Calculator` to the `@phosphor-icons/react` import and this item after the `sawt` entry:

```ts
  { id: "accounting", label: "AutoAccounting", icon: Calculator, href: "/accounting", roles: ["admin", "enterprise", "manager", "employee"] },
```

`frontend/src/components/enterprise/feature-meta.ts` — add to `FEATURE_META`:

```ts
  accounting: { label: "AutoAccounting", description: "Drop client documents and get them filed by company and quarter" },
```

`frontend/src/components/owner/feature-tabs.ts` — add to `TAB_TOGGLES`:

```ts
  { key: "accounting", label: "AutoAccounting", description: "Document intake, company databank, quarter folders" },
```

- [ ] **Step 5: Verify**

Run: `cd frontend && npm run lint && npx tsc --noEmit`
Expected: no errors (a `Record<FeatureToggleKey, …>` missing `accounting` would fail here — that is why both meta maps are updated).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/types/accounting.ts frontend/src/lib/accounting-format.ts frontend/src/lib/api.ts frontend/src/types/index.ts frontend/src/app/providers.tsx frontend/src/components/layout/Sidebar.tsx frontend/src/components/enterprise/feature-meta.ts frontend/src/components/owner/feature-tabs.ts
git commit -m "feat(accounting): frontend types, API client, nav and feature key

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Frontend components and the /accounting page

**Files:**
- Create: `frontend/src/components/accounting/CompanyForm.tsx`, `CompanyPicker.tsx`, `FolderTree.tsx`, `FileGrid.tsx`, `DocumentPanel.tsx`, `UploadReviewDialog.tsx`, `frontend/src/app/accounting/page.tsx`

**Interfaces:**
- Consumes: Task 10 types/api/helpers; `useAuth` from `@/lib/auth`; `AppBackdrop` from `@/components/layout/AppBackdrop`; `useDropzone` from `react-dropzone`.
- Produces: default-exported components with the props below; the `/accounting` route.

- [ ] **Step 1: `frontend/src/components/accounting/CompanyForm.tsx`**

```tsx
"use client";

import { useState, type FormEvent } from "react";
import { X } from "@phosphor-icons/react";
import { accountingApi } from "@/lib/api";
import { apiErrorMessage } from "@/lib/accounting-format";
import type { Company, CompanyInput } from "@/types/accounting";

const EMPTY: CompanyInput = {
  registered_name: "",
  aliases: [],
  tin: "",
  branch_code: "00000",
  rdo_code: "",
  address: "",
  zip_code: "",
  taxpayer_type: "corporation",
  vat_status: "vat",
  income_tax_option: "graduated",
  deduction_method: "itemized",
  business_type: "trading",
  is_withholding_agent: false,
  is_top_withholding_agent: false,
  has_employees: false,
  fiscal_year_end_month: 12,
  pinned: false,
};

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const INPUT = "w-full px-3 py-2 rounded-lg border border-[var(--border)] bg-[var(--bg-primary)] text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]";
const LABEL = "block text-xs font-medium text-[var(--text-secondary)] mb-1";

interface Props {
  initial?: Partial<CompanyInput>;
  companyId?: string;
  onClose: () => void;
  onSaved: (company: Company) => void;
}

export default function CompanyForm({ initial, companyId, onClose, onSaved }: Props) {
  const [form, setForm] = useState<CompanyInput>({ ...EMPTY, ...initial });
  const [aliases, setAliases] = useState((initial?.aliases ?? []).join(", "));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const set = <K extends keyof CompanyInput>(key: K, value: CompanyInput[K]) =>
    setForm((f) => ({ ...f, [key]: value }));

  async function submit(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError("");
    const payload: CompanyInput = {
      ...EMPTY,
      ...form,
      aliases: aliases.split(",").map((a) => a.trim()).filter(Boolean),
      income_tax_option: form.taxpayer_type === "individual" ? form.income_tax_option : "graduated",
    };
    try {
      const saved = companyId
        ? await accountingApi.updateCompany(companyId, payload)
        : await accountingApi.createCompany(payload);
      onSaved(saved);
    } catch (err) {
      setError(apiErrorMessage(err, "Couldn't save the company"));
    } finally {
      setSaving(false);
    }
  }

  const check = (key: "is_withholding_agent" | "is_top_withholding_agent" | "has_employees" | "pinned", text: string) => (
    <label className="flex items-center gap-2 text-sm text-[var(--text-primary)]">
      <input type="checkbox" checked={form[key]} onChange={(e) => set(key, e.target.checked)} />
      {text}
    </label>
  );

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <form
        onSubmit={submit}
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-2xl max-h-[90vh] overflow-y-auto rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] p-6"
      >
        <div className="mb-5 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-[var(--text-primary)]">
            {companyId ? "Edit company" : "Add company to databank"}
          </h2>
          <button type="button" onClick={onClose} className="rounded p-1 text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]" aria-label="Close">
            <X size={18} />
          </button>
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="sm:col-span-2">
            <label className={LABEL}>Registered name *</label>
            <input className={INPUT} required value={form.registered_name} onChange={(e) => set("registered_name", e.target.value)} />
          </div>
          <div className="sm:col-span-2">
            <label className={LABEL}>Trade names / aliases (comma-separated)</label>
            <input className={INPUT} value={aliases} onChange={(e) => setAliases(e.target.value)} placeholder="JCT, Juan Cloth Shop" />
          </div>
          <div>
            <label className={LABEL}>TIN *</label>
            <input className={INPUT} required value={form.tin} onChange={(e) => set("tin", e.target.value)} placeholder="123-456-789" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={LABEL}>Branch code</label>
              <input className={INPUT} value={form.branch_code} onChange={(e) => set("branch_code", e.target.value)} />
            </div>
            <div>
              <label className={LABEL}>RDO code</label>
              <input className={INPUT} value={form.rdo_code} onChange={(e) => set("rdo_code", e.target.value)} />
            </div>
          </div>
          <div className="sm:col-span-2 grid grid-cols-[1fr_120px] gap-3">
            <div>
              <label className={LABEL}>Registered address</label>
              <input className={INPUT} value={form.address} onChange={(e) => set("address", e.target.value)} />
            </div>
            <div>
              <label className={LABEL}>ZIP</label>
              <input className={INPUT} value={form.zip_code} onChange={(e) => set("zip_code", e.target.value)} />
            </div>
          </div>
          <div>
            <label className={LABEL}>Taxpayer type</label>
            <select className={INPUT} value={form.taxpayer_type} onChange={(e) => set("taxpayer_type", e.target.value as CompanyInput["taxpayer_type"])}>
              <option value="corporation">Corporation</option>
              <option value="partnership">Partnership</option>
              <option value="individual">Individual</option>
            </select>
          </div>
          <div>
            <label className={LABEL}>Tax registration</label>
            <select className={INPUT} value={form.vat_status} onChange={(e) => set("vat_status", e.target.value as CompanyInput["vat_status"])}>
              <option value="vat">VAT-registered</option>
              <option value="non_vat">Non-VAT</option>
            </select>
          </div>
          {form.taxpayer_type === "individual" && (
            <div>
              <label className={LABEL}>Income tax option</label>
              <select className={INPUT} value={form.income_tax_option} onChange={(e) => set("income_tax_option", e.target.value as CompanyInput["income_tax_option"])}>
                <option value="graduated">Graduated rates</option>
                <option value="eight_percent">8% on gross</option>
              </select>
            </div>
          )}
          <div>
            <label className={LABEL}>Deduction method</label>
            <select className={INPUT} value={form.deduction_method} onChange={(e) => set("deduction_method", e.target.value as CompanyInput["deduction_method"])}>
              <option value="itemized">Itemized</option>
              <option value="osd">OSD (40%)</option>
            </select>
          </div>
          <div>
            <label className={LABEL}>Business type</label>
            <select className={INPUT} value={form.business_type} onChange={(e) => set("business_type", e.target.value as CompanyInput["business_type"])}>
              <option value="trading">Trading</option>
              <option value="manufacturing">Manufacturing</option>
              <option value="services">Services</option>
            </select>
          </div>
          <div>
            <label className={LABEL}>Fiscal year ends</label>
            <select className={INPUT} value={form.fiscal_year_end_month} onChange={(e) => set("fiscal_year_end_month", Number(e.target.value))}>
              {MONTHS.map((m, i) => (
                <option key={m} value={i + 1}>{m}</option>
              ))}
            </select>
          </div>
          <div className="sm:col-span-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
            {check("is_withholding_agent", "Withholds tax on supplier payments")}
            {check("is_top_withholding_agent", "Top Withholding Agent")}
            {check("has_employees", "Has employees")}
            {check("pinned", "Pin to top of lists")}
          </div>
        </div>

        {error && <p className="mt-4 text-sm text-red-600 dark:text-red-400">{error}</p>}

        <div className="mt-6 flex justify-end gap-2">
          <button type="button" onClick={onClose} className="rounded-lg border border-[var(--border)] px-4 py-2 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)]">
            Cancel
          </button>
          <button type="submit" disabled={saving} className="rounded-lg bg-[var(--accent)] px-4 py-2 text-sm font-medium text-white hover:bg-[var(--accent-hover)] disabled:opacity-60">
            {saving ? "Saving…" : companyId ? "Save changes" : "Add to databank"}
          </button>
        </div>
      </form>
    </div>
  );
}
```

- [ ] **Step 2: `frontend/src/components/accounting/CompanyPicker.tsx`**

```tsx
"use client";

import type { Company } from "@/types/accounting";

interface Props {
  companies: Company[];
  value: string; // "auto" or a company id
  onChange: (value: string) => void;
}

export default function CompanyPicker({ companies, value, onChange }: Props) {
  const pinned = companies.filter((c) => c.pinned);
  const rest = companies.filter((c) => !c.pinned);
  const current = companies.some((c) => c.id === value) ? value : "auto";

  return (
    <label className="flex items-center gap-2 rounded-lg border border-[var(--accent)] bg-[var(--accent-subtle)] px-3 py-1.5 text-sm">
      <span className="text-[var(--text-secondary)]">Drop files for:</span>
      <select
        value={current}
        onChange={(e) => onChange(e.target.value)}
        className="max-w-[220px] bg-transparent font-medium text-[var(--text-primary)] focus:outline-none"
      >
        <option value="auto">Auto-detect</option>
        {pinned.length > 0 && (
          <optgroup label="Pinned">
            {pinned.map((c) => (
              <option key={c.id} value={c.id}>{c.registered_name}</option>
            ))}
          </optgroup>
        )}
        {rest.length > 0 && (
          <optgroup label="All companies">
            {rest.map((c) => (
              <option key={c.id} value={c.id}>{c.registered_name}</option>
            ))}
          </optgroup>
        )}
      </select>
    </label>
  );
}
```

- [ ] **Step 3: `frontend/src/components/accounting/FolderTree.tsx`**

```tsx
"use client";

import { useEffect, useState } from "react";
import { Buildings, CaretDown, CaretRight, Plus } from "@phosphor-icons/react";
import type { FolderRef, TreeCompany } from "@/types/accounting";

interface Props {
  tree: TreeCompany[];
  selected: FolderRef | null;
  onSelect: (ref: FolderRef) => void;
  canManage: boolean;
  onAddCompany: () => void;
}

const ROW = "flex w-full items-center gap-1.5 rounded-md px-2 py-1.5 text-left text-sm hover:bg-[var(--bg-hover)]";

export default function FolderTree({ tree, selected, onSelect, canManage, onAddCompany }: Props) {
  const [open, setOpen] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (!selected) return;
    setOpen((prev) => (prev.has(selected.companyId) ? prev : new Set(prev).add(selected.companyId)));
  }, [selected]);

  const toggle = (id: string) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const isSelected = (ref: FolderRef) =>
    selected?.companyId === ref.companyId && selected.year === ref.year && selected.quarter === ref.quarter;

  const leaf = (ref: FolderRef, label: string, count: number, review: number) => (
    <button
      onClick={() => onSelect(ref)}
      className={`${ROW} ${isSelected(ref) ? "bg-[var(--accent-subtle)] font-semibold text-[var(--text-primary)]" : "text-[var(--text-primary)]"}`}
    >
      <span className="truncate">{label}</span>
      <span className="ml-auto text-xs text-[var(--text-secondary)]">{count}</span>
      {review > 0 && (
        <span className="rounded-full bg-amber-100 px-1.5 text-[11px] font-medium text-amber-800 dark:bg-amber-500/15 dark:text-amber-300">
          {review}
        </span>
      )}
    </button>
  );

  const company = (c: TreeCompany) => (
    <li key={c.id}>
      <button onClick={() => toggle(c.id)} className={`${ROW} text-[var(--text-primary)]`}>
        {open.has(c.id) ? <CaretDown size={12} /> : <CaretRight size={12} />}
        <Buildings size={15} className="shrink-0 text-[var(--text-secondary)]" />
        <span className="truncate font-medium">{c.registered_name}</span>
      </button>
      {open.has(c.id) && (
        <ul className="ml-4 border-l border-[var(--border)] pl-2">
          {c.years.length === 0 && c.undated_count === 0 && (
            <li className="px-2 py-1 text-xs text-[var(--text-secondary)]">No documents yet</li>
          )}
          {c.years.map((y) => (
            <li key={y.year}>
              <div className="px-2 pt-1.5 text-xs font-semibold text-[var(--text-secondary)]">{y.year}</div>
              <ul>
                {y.quarters.map((q) => (
                  <li key={q.quarter}>
                    {leaf({ companyId: c.id, year: q.year, quarter: q.quarter }, q.label, q.document_count, q.review_count)}
                  </li>
                ))}
              </ul>
            </li>
          ))}
          {c.undated_count > 0 && (
            <li>{leaf({ companyId: c.id, year: null, quarter: null }, "Undated", c.undated_count, c.undated_count)}</li>
          )}
        </ul>
      )}
    </li>
  );

  const pinned = tree.filter((c) => c.pinned);
  const others = tree.filter((c) => !c.pinned);
  const heading = "px-2 pb-1 pt-2 text-[11px] font-semibold uppercase tracking-wide text-[var(--text-secondary)]";

  return (
    <nav aria-label="Companies">
      {pinned.length > 0 && (
        <>
          <p className={heading}>Pinned</p>
          <ul>{pinned.map(company)}</ul>
        </>
      )}
      {others.length > 0 && (
        <>
          <p className={heading}>{pinned.length ? "All companies" : "Companies"}</p>
          <ul>{others.map(company)}</ul>
        </>
      )}
      {tree.length === 0 && (
        <p className="px-2 py-3 text-sm text-[var(--text-secondary)]">No companies yet. Drop documents or add a company.</p>
      )}
      {canManage && (
        <button onClick={onAddCompany} className="mt-3 flex items-center gap-1.5 px-2 text-sm font-semibold text-[var(--accent)]">
          <Plus size={14} /> Add company
        </button>
      )}
    </nav>
  );
}
```

- [ ] **Step 4: `frontend/src/components/accounting/FileGrid.tsx`**

```tsx
"use client";

import { FolderSimple } from "@phosphor-icons/react";
import { CATEGORY_LABELS, counterpartyName, formatPeso } from "@/lib/accounting-format";
import type { AADocument, Folder } from "@/types/accounting";

const TILES = ["sales", "purchases", "expenses", "payroll", "2307", "unsorted", "review"] as const;

interface Props {
  folder: Folder;
  category: string | null;
  onCategory: (category: string | null) => void;
  onOpen: (doc: AADocument) => void;
  onEditCompany?: () => void;
}

function inCategory(doc: AADocument, category: string): boolean {
  if (category === "review") return doc.needs_review && !doc.reviewed && !doc.excluded;
  return doc.category === category;
}

export default function FileGrid({ folder, category, onCategory, onOpen, onEditCompany }: Props) {
  const docs = category ? folder.documents.filter((d) => inCategory(d, category)) : [];

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-2 text-sm">
        <button onClick={() => onCategory(null)} className="font-semibold text-[var(--text-primary)] hover:underline">
          {folder.company.registered_name} / {folder.label}
        </button>
        {category && <span className="text-[var(--text-secondary)]">/ {CATEGORY_LABELS[category]}</span>}
        <div className="ml-auto flex items-center gap-3">
          {folder.counts.review > 0 && (
            <span className="rounded-full bg-amber-100 px-2.5 py-0.5 text-xs font-medium text-amber-800 dark:bg-amber-500/15 dark:text-amber-300">
              {folder.counts.review} to review
            </span>
          )}
          {onEditCompany && (
            <button onClick={onEditCompany} className="text-xs text-[var(--text-secondary)] underline hover:text-[var(--text-primary)]">
              Edit company
            </button>
          )}
        </div>
      </div>

      {category === null ? (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {TILES.map((key) => (
            <button
              key={key}
              onClick={() => onCategory(key)}
              className="rounded-xl border border-[var(--border)] p-3 text-left transition-colors hover:border-[var(--accent)]"
            >
              <FolderSimple size={22} className="text-[var(--text-secondary)]" weight="fill" />
              <div className="mt-2 text-sm font-semibold text-[var(--text-primary)]">{CATEGORY_LABELS[key]}</div>
              <div className="text-xs text-[var(--text-secondary)]">
                {folder.counts[key] ?? 0} {key === "review" ? "open" : "documents"}
              </div>
            </button>
          ))}
        </div>
      ) : docs.length === 0 ? (
        <p className="py-10 text-center text-sm text-[var(--text-secondary)]">Nothing here.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-[var(--text-secondary)]">
                <th className="py-2 pr-3 font-medium">Date</th>
                <th className="py-2 pr-3 font-medium">Document</th>
                <th className="py-2 pr-3 font-medium">Counterparty</th>
                <th className="py-2 pr-3 text-right font-medium">Total</th>
                <th className="py-2 pr-3 text-right font-medium">VAT</th>
                <th className="py-2" />
              </tr>
            </thead>
            <tbody>
              {docs.map((d) => (
                <tr
                  key={d.id}
                  onClick={() => onOpen(d)}
                  className="cursor-pointer border-t border-[var(--border)] text-[var(--text-primary)] hover:bg-[var(--bg-hover)]"
                >
                  <td className="py-2 pr-3 whitespace-nowrap">{d.doc_date ?? "—"}</td>
                  <td className="py-2 pr-3">
                    {d.document_title || CATEGORY_LABELS[d.category]}
                    {d.doc_number && <span className="text-[var(--text-secondary)]"> #{d.doc_number}</span>}
                  </td>
                  <td className="py-2 pr-3">{counterpartyName(d) || "—"}</td>
                  <td className="py-2 pr-3 text-right tabular-nums">{formatPeso(d.gross_amount)}</td>
                  <td className="py-2 pr-3 text-right tabular-nums">{formatPeso(d.vat_amount)}</td>
                  <td className="py-2 text-right">
                    {d.excluded ? (
                      <span className="rounded-full border border-[var(--border)] px-2 py-0.5 text-xs text-[var(--text-secondary)]">Excluded</span>
                    ) : d.needs_review && !d.reviewed ? (
                      <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800 dark:bg-amber-500/15 dark:text-amber-300">Review</span>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 5: `frontend/src/components/accounting/DocumentPanel.tsx`**

```tsx
"use client";

import { useEffect, useState } from "react";
import { X } from "@phosphor-icons/react";
import { accountingApi } from "@/lib/api";
import { ACCOUNTS, ACCOUNT_LABELS, CATEGORY_LABELS, REASON_LABELS, apiErrorMessage } from "@/lib/accounting-format";
import type { AADocument, DocumentPatch } from "@/types/accounting";

const AMOUNTS = [
  ["gross_amount", "Total"],
  ["vatable_amount", "VATable"],
  ["vat_amount", "VAT"],
  ["exempt_amount", "VAT-exempt"],
  ["zero_rated_amount", "Zero-rated"],
  ["withholding_amount", "Tax withheld"],
] as const;
const AMOUNT_KEYS = new Set<string>(AMOUNTS.map(([k]) => k));
const CATEGORIES = ["sales", "purchases", "expenses", "payroll", "2307", "unsorted"] as const;
const INPUT = "w-full px-2.5 py-1.5 rounded-md border border-[var(--border)] bg-[var(--bg-primary)] text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]";
const LABEL = "block text-[11px] font-medium text-[var(--text-secondary)] mb-1";
const BTN = "rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-60";

type Draft = Record<string, string>;

function toDraft(doc: AADocument): Draft {
  return {
    doc_date: doc.doc_date ?? "",
    doc_number: doc.doc_number,
    category: doc.category,
    account: doc.account,
    seller_name: doc.seller_name,
    seller_tin: doc.seller_tin,
    buyer_name: doc.buyer_name,
    buyer_tin: doc.buyer_tin,
    gross_amount: doc.gross_amount,
    vatable_amount: doc.vatable_amount,
    vat_amount: doc.vat_amount,
    exempt_amount: doc.exempt_amount,
    zero_rated_amount: doc.zero_rated_amount,
    withholding_amount: doc.withholding_amount,
  };
}

interface Props {
  doc: AADocument;
  onClose: () => void;
  onChanged: (doc: AADocument) => void;
  onDeleted: (id: string) => void;
}

export default function DocumentPanel({ doc, onClose, onChanged, onDeleted }: Props) {
  const [draft, setDraft] = useState<Draft>(() => toDraft(doc));
  const [images, setImages] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [moveYear, setMoveYear] = useState(String(doc.period_year ?? new Date().getFullYear()));
  const [moveQuarter, setMoveQuarter] = useState(String(doc.period_quarter ?? 1));

  useEffect(() => {
    setDraft(toDraft(doc));
    setConfirmDelete(false);
  }, [doc]);

  useEffect(() => {
    let cancelled = false;
    const urls: string[] = [];
    setImages([]);
    const last = Math.min(doc.page_end, doc.page_start + 4);
    (async () => {
      for (let p = doc.page_start; p <= last; p++) {
        try {
          const blob = await accountingApi.pageImage(doc.file_id, p);
          if (cancelled) return;
          const url = URL.createObjectURL(blob);
          urls.push(url);
          setImages((prev) => [...prev, url]);
        } catch {
          // Page previews are best-effort; the fields still load.
        }
      }
    })();
    return () => {
      cancelled = true;
      urls.forEach((u) => URL.revokeObjectURL(u));
    };
  }, [doc.file_id, doc.page_start, doc.page_end]);

  async function save(extra: DocumentPatch = {}) {
    const initial = toDraft(doc);
    const patch: DocumentPatch = { ...extra };
    for (const [key, value] of Object.entries(draft)) {
      if (value === initial[key]) continue;
      if (key === "doc_date") patch[key] = value || null;
      else if (AMOUNT_KEYS.has(key)) patch[key] = value.trim() || "0";
      else patch[key] = value;
    }
    if (Object.keys(patch).length === 0) return;
    setBusy(true);
    setError("");
    try {
      onChanged(await accountingApi.updateDocument(doc.id, patch));
    } catch (e) {
      setError(apiErrorMessage(e, "Couldn't save the document"));
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!confirmDelete) {
      setConfirmDelete(true);
      return;
    }
    setBusy(true);
    try {
      await accountingApi.deleteDocument(doc.id);
      onDeleted(doc.id);
    } catch (e) {
      setError(apiErrorMessage(e, "Couldn't delete the document"));
      setBusy(false);
    }
  }

  const field = (key: string, label: string, type = "text") => (
    <div>
      <label className={LABEL}>{label}</label>
      <input
        type={type}
        className={INPUT}
        value={draft[key] ?? ""}
        onChange={(e) => setDraft((d) => ({ ...d, [key]: e.target.value }))}
      />
    </div>
  );

  const openReasons = doc.needs_review && !doc.reviewed ? doc.review_reasons : [];

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/30" onClick={onClose}>
      <aside
        onClick={(e) => e.stopPropagation()}
        className="h-full w-full max-w-xl overflow-y-auto border-l border-[var(--border)] bg-[var(--bg-secondary)] p-5"
      >
        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold text-[var(--text-primary)]">
              {doc.document_title || CATEGORY_LABELS[doc.category]} {doc.doc_number && `#${doc.doc_number}`}
            </h2>
            <p className="text-xs text-[var(--text-secondary)]">
              {doc.period_year
                ? `Filed in ${doc.period_year} Q${doc.period_quarter}${doc.period_locked ? " (moved by hand)" : ""}`
                : "Undated"}
              {" · "}pages {doc.page_start}–{doc.page_end} · confidence {Math.round(doc.confidence)}%
            </p>
          </div>
          <button onClick={onClose} className="rounded p-1 text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]" aria-label="Close">
            <X size={18} />
          </button>
        </div>

        {openReasons.length > 0 && (
          <ul className="mb-4 space-y-1 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-500/40 dark:bg-amber-500/10 dark:text-amber-200">
            {openReasons.map((r) => (
              <li key={r}>• {REASON_LABELS[r] ?? r}</li>
            ))}
          </ul>
        )}

        <div className="mb-4 space-y-2">
          {images.map((src, i) => (
            // eslint-disable-next-line @next/next/no-img-element
            <img key={src} src={src} alt={`Page ${doc.page_start + i}`} className="w-full rounded-lg border border-[var(--border)]" />
          ))}
          {images.length === 0 && <div className="h-40 animate-pulse rounded-lg bg-[var(--bg-primary)]" />}
        </div>

        <div className="grid grid-cols-2 gap-3">
          {field("doc_date", "Document date", "date")}
          {field("doc_number", "Document no.")}
          <div>
            <label className={LABEL}>Folder</label>
            <select className={INPUT} value={draft.category} onChange={(e) => setDraft((d) => ({ ...d, category: e.target.value }))}>
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>{CATEGORY_LABELS[c]}</option>
              ))}
            </select>
          </div>
          <div>
            <label className={LABEL}>Account</label>
            <select className={INPUT} value={draft.account} onChange={(e) => setDraft((d) => ({ ...d, account: e.target.value }))}>
              {ACCOUNTS.map((a) => (
                <option key={a} value={a}>{ACCOUNT_LABELS[a]}</option>
              ))}
            </select>
          </div>
          {field("seller_name", "Seller")}
          {field("seller_tin", "Seller TIN")}
          {field("buyer_name", "Buyer")}
          {field("buyer_tin", "Buyer TIN")}
          {AMOUNTS.map(([key, label]) => (
            <div key={key}>{field(key, label)}</div>
          ))}
        </div>

        <div className="mt-4 rounded-lg border border-[var(--border)] p-3">
          <p className="mb-2 text-xs font-medium text-[var(--text-secondary)]">Move to another quarter</p>
          <div className="flex flex-wrap items-center gap-2">
            <input type="number" min={2000} max={2100} className={`${INPUT} w-24`} value={moveYear} onChange={(e) => setMoveYear(e.target.value)} />
            <select className={`${INPUT} w-20`} value={moveQuarter} onChange={(e) => setMoveQuarter(e.target.value)}>
              {[1, 2, 3, 4].map((q) => (
                <option key={q} value={q}>Q{q}</option>
              ))}
            </select>
            <button className={BTN} disabled={busy} onClick={() => save({ period_year: Number(moveYear), period_quarter: Number(moveQuarter) })}>
              Move
            </button>
            {doc.period_locked && (
              <button className={BTN} disabled={busy} onClick={() => save({ period_year: null, period_quarter: null })}>
                Use document date
              </button>
            )}
          </div>
        </div>

        {error && <p className="mt-3 text-sm text-red-600 dark:text-red-400">{error}</p>}

        <div className="mt-5 flex flex-wrap gap-2">
          <button
            className="rounded-lg bg-[var(--accent)] px-3 py-1.5 text-sm font-medium text-white hover:bg-[var(--accent-hover)] disabled:opacity-60"
            disabled={busy}
            onClick={() => save()}
          >
            Save
          </button>
          {doc.needs_review && !doc.reviewed && (
            <button className={BTN} disabled={busy} onClick={() => save({ reviewed: true })}>
              Mark reviewed
            </button>
          )}
          <button className={BTN} disabled={busy} onClick={() => save({ excluded: !doc.excluded })}>
            {doc.excluded ? "Include again" : "Exclude from computation"}
          </button>
          <button
            className="ml-auto rounded-lg border border-red-300 px-3 py-1.5 text-sm font-medium text-red-700 hover:bg-red-50 disabled:opacity-60 dark:border-red-500/40 dark:text-red-300 dark:hover:bg-red-500/10"
            disabled={busy}
            onClick={remove}
          >
            {confirmDelete ? "Click again to delete" : "Delete"}
          </button>
        </div>
      </aside>
    </div>
  );
}
```

- [ ] **Step 6: `frontend/src/components/accounting/UploadReviewDialog.tsx`**

```tsx
"use client";

import { useState } from "react";
import { CheckCircle, X } from "@phosphor-icons/react";
import CompanyForm from "@/components/accounting/CompanyForm";
import { apiErrorMessage, formatTin } from "@/lib/accounting-format";
import type { Company, ConfirmAssignment, Upload, UploadGroup } from "@/types/accounting";

type Decision = { kind: "company"; companyId: string } | { kind: "skip" };

interface Props {
  upload: Upload;
  companies: Company[];
  canManage: boolean;
  onCompanyCreated: (company: Company) => void;
  onConfirm: (assignments: ConfirmAssignment[]) => Promise<void>;
  onClose: () => void;
}

const BTN = "rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-50";
const SELECT = "rounded-lg border border-[var(--border)] bg-[var(--bg-primary)] px-2 py-1.5 text-sm text-[var(--text-primary)]";

export default function UploadReviewDialog({ upload, companies, canManage, onCompanyCreated, onConfirm, onClose }: Props) {
  const [decisions, setDecisions] = useState<Record<string, Decision>>({});
  const [excluded, setExcluded] = useState<Set<string>>(new Set());
  const [expanded, setExpanded] = useState<string | null>(null);
  const [newCompanyFor, setNewCompanyFor] = useState<UploadGroup | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const duplicates = upload.files.filter((f) => f.status === "duplicate").length;
  const allDecided = upload.groups.every((g) => decisions[g.key]);
  const decide = (key: string, d: Decision) => setDecisions((prev) => ({ ...prev, [key]: d }));
  const nameOf = (id: string) => companies.find((c) => c.id === id)?.registered_name ?? "selected company";

  const toggleFile = (id: string) =>
    setExcluded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  async function submit() {
    const assignments: ConfirmAssignment[] = [];
    const skipped = [...excluded];
    for (const g of upload.groups) {
      const ids = g.file_ids.filter((id) => !excluded.has(id));
      const d = decisions[g.key];
      if (!ids.length || !d) continue;
      if (d.kind === "skip") skipped.push(...ids);
      else assignments.push({ file_ids: ids, company_id: d.companyId });
    }
    if (skipped.length) assignments.push({ file_ids: skipped, skip: true });
    setSubmitting(true);
    setError("");
    try {
      await onConfirm(assignments);
    } catch (e) {
      setError(apiErrorMessage(e, "Couldn't confirm the upload"));
      setSubmitting(false);
    }
  }

  const chooseOther = (g: UploadGroup) => (
    <select
      className={SELECT}
      value=""
      onChange={(e) => {
        if (e.target.value) decide(g.key, { kind: "company", companyId: e.target.value });
      }}
    >
      <option value="">{g.company ? "Choose another company…" : "Choose existing company…"}</option>
      {companies.map((c) => (
        <option key={c.id} value={c.id}>{c.registered_name}</option>
      ))}
    </select>
  );

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-2xl max-h-[90vh] overflow-y-auto rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] p-6">
        <div className="mb-1 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-[var(--text-primary)]">Which company are these for?</h2>
          <button onClick={onClose} className="rounded p-1 text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]" aria-label="Close">
            <X size={18} />
          </button>
        </div>
        <p className="mb-5 text-sm text-[var(--text-secondary)]">
          Confirm each group before the documents are read and filed.
          {duplicates > 0 && ` ${duplicates} file${duplicates === 1 ? " was" : "s were"} already uploaded and skipped.`}
        </p>

        <div className="space-y-4">
          {upload.groups.map((g) => {
            const d = decisions[g.key];
            const company = g.company;
            const count = g.file_ids.filter((id) => !excluded.has(id)).length;
            return (
              <div key={g.key} className="rounded-xl border border-[var(--border)] p-4">
                {g.company ? (
                  <p className="text-sm text-[var(--text-primary)]">
                    These {count} file{count === 1 ? "" : "s"} look like they belong to{" "}
                    <strong>{g.company.registered_name}</strong> (TIN {formatTin(g.company.tin)})
                    {g.level === "likely" && <span className="text-[var(--text-secondary)]"> — matched by name</span>}. Correct?
                  </p>
                ) : (
                  <p className="text-sm text-[var(--text-primary)]">
                    We couldn&apos;t find this company in your databank
                    {g.detected_name || g.detected_tin ? (
                      <>
                        : <strong>{g.detected_name || "Unnamed"}</strong>
                        {g.detected_tin && ` (TIN ${formatTin(g.detected_tin)})`}
                      </>
                    ) : null}
                    . Is this a new company? ({count} file{count === 1 ? "" : "s"})
                  </p>
                )}

                <div className="mt-3 flex flex-wrap items-center gap-2">
                  {company && (
                    <button className={BTN} onClick={() => decide(g.key, { kind: "company", companyId: company.id })}>
                      Yes, that&apos;s right
                    </button>
                  )}
                  {!g.company && (
                    <button
                      className={BTN}
                      disabled={!canManage}
                      title={canManage ? undefined : "Ask an owner or manager to add this company"}
                      onClick={() => setNewCompanyFor(g)}
                    >
                      Add to databank
                    </button>
                  )}
                  {chooseOther(g)}
                  <button className={BTN} onClick={() => decide(g.key, { kind: "skip" })}>
                    Skip these files
                  </button>
                  <button className="ml-auto text-xs text-[var(--text-secondary)] underline" onClick={() => setExpanded(expanded === g.key ? null : g.key)}>
                    {expanded === g.key ? "Hide files" : "Show files"}
                  </button>
                </div>

                {d && (
                  <p className="mt-2 flex items-center gap-1.5 text-sm font-medium text-[var(--accent)]">
                    <CheckCircle size={16} weight="fill" />
                    {d.kind === "skip" ? "Will be skipped" : `Filing to ${nameOf(d.companyId)}`}
                  </p>
                )}

                {expanded === g.key && (
                  <ul className="mt-3 space-y-1 border-t border-[var(--border)] pt-3">
                    {g.file_ids.map((id, i) => (
                      <li key={id}>
                        <label className="flex items-center gap-2 text-sm text-[var(--text-primary)]">
                          <input type="checkbox" checked={!excluded.has(id)} onChange={() => toggleFile(id)} />
                          {g.file_names[i]}
                        </label>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            );
          })}
        </div>

        {error && <p className="mt-4 text-sm text-red-600 dark:text-red-400">{error}</p>}

        <div className="mt-6 flex justify-end gap-2">
          <button className={BTN} onClick={onClose}>Decide later</button>
          <button
            className="rounded-lg bg-[var(--accent)] px-4 py-2 text-sm font-medium text-white hover:bg-[var(--accent-hover)] disabled:opacity-50"
            disabled={!allDecided || submitting}
            onClick={submit}
          >
            {submitting ? "Starting…" : "Confirm and file"}
          </button>
        </div>
      </div>

      {newCompanyFor && (
        <CompanyForm
          initial={{
            registered_name: newCompanyFor.detected_name,
            tin: newCompanyFor.detected_tin,
            address: newCompanyFor.detected_address,
          }}
          onClose={() => setNewCompanyFor(null)}
          onSaved={(company) => {
            onCompanyCreated(company);
            decide(newCompanyFor.key, { kind: "company", companyId: company.id });
            setNewCompanyFor(null);
          }}
        />
      )}
    </div>
  );
}
```

- [ ] **Step 7: `frontend/src/app/accounting/page.tsx`**

```tsx
"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useDropzone } from "react-dropzone";
import { MagnifyingGlass, Spinner, UploadSimple } from "@phosphor-icons/react";
import AppBackdrop from "@/components/layout/AppBackdrop";
import CompanyForm from "@/components/accounting/CompanyForm";
import CompanyPicker from "@/components/accounting/CompanyPicker";
import DocumentPanel from "@/components/accounting/DocumentPanel";
import FileGrid from "@/components/accounting/FileGrid";
import FolderTree from "@/components/accounting/FolderTree";
import UploadReviewDialog from "@/components/accounting/UploadReviewDialog";
import { accountingApi } from "@/lib/api";
import { apiErrorMessage } from "@/lib/accounting-format";
import { useAuth } from "@/lib/auth";
import type {
  AADocument,
  Company,
  CompanyInput,
  ConfirmAssignment,
  Folder,
  FolderRef,
  TreeCompany,
  Upload,
} from "@/types/accounting";

const PICKER_KEY = "aa:lastPicker";
const ACCEPT = { "application/pdf": [".pdf"], "image/png": [".png"], "image/jpeg": [".jpg", ".jpeg"] };
const BUSY: Upload["status"][] = ["detecting", "confirming", "extracting"];

export default function AccountingPage() {
  const { user } = useAuth();
  const canManage = user?.role === "admin" || user?.role === "enterprise" || user?.role === "manager";

  const [companies, setCompanies] = useState<Company[]>([]);
  const [tree, setTree] = useState<TreeCompany[]>([]);
  const [search, setSearch] = useState("");
  const [picker, setPicker] = useState("auto");
  const [selected, setSelected] = useState<FolderRef | null>(null);
  const [folder, setFolder] = useState<Folder | null>(null);
  const [category, setCategory] = useState<string | null>(null);
  const [openDoc, setOpenDoc] = useState<AADocument | null>(null);
  const [upload, setUpload] = useState<Upload | null>(null);
  const [reviewOpen, setReviewOpen] = useState(false);
  const [companyForm, setCompanyForm] = useState<{ initial?: Partial<CompanyInput>; id?: string } | null>(null);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    try {
      setPicker(localStorage.getItem(PICKER_KEY) || "auto");
    } catch {
      // storage unavailable (private mode) — keep auto-detect
    }
  }, []);

  const choosePicker = (value: string) => {
    setPicker(value);
    try {
      localStorage.setItem(PICKER_KEY, value);
    } catch {
      // not persisted; still works for this visit
    }
  };

  const loadCompanies = useCallback(async () => setCompanies(await accountingApi.listCompanies()), []);
  const loadTree = useCallback(async () => setTree(await accountingApi.tree()), []);
  const loadFolder = useCallback(async (ref: FolderRef | null) => {
    setFolder(ref ? await accountingApi.folder(ref.companyId, ref.year, ref.quarter) : null);
  }, []);

  useEffect(() => {
    Promise.all([loadCompanies(), loadTree()]).catch((e) => setError(apiErrorMessage(e, "Couldn't load AutoAccounting")));
  }, [loadCompanies, loadTree]);

  useEffect(() => {
    setCategory(null);
    loadFolder(selected).catch((e) => setError(apiErrorMessage(e, "Couldn't open the folder")));
  }, [selected, loadFolder]);

  // Poll while the server is working on the active upload.
  const uploadId = upload?.id;
  const uploadStatus = upload?.status;
  useEffect(() => {
    if (!uploadId || !uploadStatus || !BUSY.includes(uploadStatus)) return;
    const timer = setInterval(() => {
      accountingApi.getUpload(uploadId).then(setUpload).catch((e) => setError(apiErrorMessage(e)));
    }, 2000);
    return () => clearInterval(timer);
  }, [uploadId, uploadStatus]);

  // React once to each status change.
  const lastStatus = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (!upload || upload.status === lastStatus.current) return;
    lastStatus.current = upload.status;
    if (upload.status === "awaiting_confirmation") setReviewOpen(true);
    if (upload.status === "failed") setError("Processing failed. Try uploading the files again.");
    if (upload.status === "done") {
      const filed = upload.files.filter((f) => f.status === "extracted").length;
      const failed = upload.files.filter((f) => f.status === "error").length;
      const dupes = upload.files.filter((f) => f.status === "duplicate").length;
      const parts = [`${filed} file${filed === 1 ? "" : "s"} filed`];
      if (dupes) parts.push(`${dupes} already uploaded`);
      if (failed) parts.push(`${failed} couldn't be read`);
      setNotice(parts.join(" · "));
      loadTree().catch(() => undefined);
      loadFolder(selected).catch(() => undefined);
    }
  }, [upload, loadTree, loadFolder, selected]);

  const target = picker !== "auto" ? picker : selected?.companyId ?? null;
  const targetName = companies.find((c) => c.id === target)?.registered_name;

  const onDrop = useCallback(
    async (files: File[]) => {
      if (!files.length) return;
      if (upload && (BUSY.includes(upload.status) || upload.status === "awaiting_confirmation")) {
        setError("Finish the current upload before dropping more files.");
        return;
      }
      setError("");
      setNotice("");
      try {
        setUpload(await accountingApi.upload(files, target ?? undefined));
      } catch (e) {
        setError(apiErrorMessage(e, "Upload failed"));
      }
    },
    [target, upload],
  );

  const { getRootProps, getInputProps, isDragActive, open } = useDropzone({
    onDrop,
    onDropRejected: () => setError("Only PDF, PNG and JPG files can be dropped here."),
    accept: ACCEPT,
    noClick: true,
    noKeyboard: true,
  });

  const filteredTree = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return tree;
    const digits = q.replace(/\D/g, "");
    return tree.filter((c) => c.registered_name.toLowerCase().includes(q) || (digits.length > 0 && c.tin.includes(digits)));
  }, [tree, search]);

  async function confirm(assignments: ConfirmAssignment[]) {
    if (!upload) return;
    setUpload(await accountingApi.confirmUpload(upload.id, assignments));
    setReviewOpen(false);
  }

  async function companySaved() {
    setCompanyForm(null);
    await Promise.all([loadCompanies(), loadTree()]);
  }

  const editCompany = (id: string) => {
    const c = companies.find((x) => x.id === id);
    if (c) setCompanyForm({ initial: c, id });
  };

  const refreshAfterDocChange = () => {
    loadFolder(selected).catch(() => undefined);
    loadTree().catch(() => undefined);
  };

  return (
    <div className="lp relative min-h-screen">
      <AppBackdrop />
      <div className="p-4 sm:p-8 page-enter">
        <div className="mb-6 flex flex-wrap items-center gap-3">
          <div className="mr-auto">
            <h1 className="text-2xl font-bold text-[var(--text-primary)]">AutoAccounting</h1>
            <p className="mt-1 text-sm text-[var(--text-secondary)]">
              Drop a client&apos;s receipts and invoices. They&apos;re matched to the company and filed by quarter.
            </p>
          </div>
          <label className="relative">
            <MagnifyingGlass size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-secondary)]" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search companies or TINs"
              className="w-64 rounded-full border border-[var(--border)] bg-[var(--bg-secondary)] py-1.5 pl-8 pr-3 text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]"
            />
          </label>
          <CompanyPicker companies={companies} value={picker} onChange={choosePicker} />
        </div>

        {error && (
          <div className="mb-4 rounded-lg border border-red-300 bg-red-50 px-4 py-2 text-sm text-red-700 dark:border-red-500/40 dark:bg-red-500/10 dark:text-red-300">
            {error}
          </div>
        )}
        {notice && (
          <div className="mb-4 rounded-lg border border-[var(--border)] bg-[var(--accent-subtle)] px-4 py-2 text-sm text-[var(--text-primary)]">
            {notice}
          </div>
        )}
        {upload && BUSY.includes(upload.status) && (
          <div className="mb-4 flex items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] px-4 py-2 text-sm text-[var(--text-primary)]">
            <Spinner size={16} className="animate-spin" />
            {upload.status === "detecting" ? "Detecting companies" : "Reading and filing documents"} ·{" "}
            {upload.processed_files}/{upload.total_files}
          </div>
        )}
        {upload?.status === "awaiting_confirmation" && !reviewOpen && (
          <div className="mb-4 flex items-center gap-3 rounded-lg border border-amber-300 bg-amber-50 px-4 py-2 text-sm text-amber-900 dark:border-amber-500/40 dark:bg-amber-500/10 dark:text-amber-200">
            Your last drop is waiting for you to confirm the company.
            <button className="font-semibold underline" onClick={() => setReviewOpen(true)}>Review now</button>
          </div>
        )}

        <div className="grid grid-cols-1 gap-4 md:grid-cols-[250px_1fr]">
          <aside className="h-fit rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] p-3">
            <FolderTree
              tree={filteredTree}
              selected={selected}
              onSelect={setSelected}
              canManage={canManage}
              onAddCompany={() => setCompanyForm({})}
            />
          </aside>

          <section
            {...getRootProps()}
            className={`relative min-h-[420px] rounded-xl border bg-[var(--bg-secondary)] p-4 ${isDragActive ? "border-[var(--accent)] ring-2 ring-[var(--accent)]" : "border-[var(--border)]"}`}
          >
            <input {...getInputProps()} />
            {folder ? (
              <FileGrid
                folder={folder}
                category={category}
                onCategory={setCategory}
                onOpen={setOpenDoc}
                onEditCompany={canManage ? () => editCompany(folder.company.id) : undefined}
              />
            ) : (
              <p className="py-10 text-center text-sm text-[var(--text-secondary)]">
                Pick a quarter on the left, or drop documents to get started.
              </p>
            )}

            <div className="mt-6 rounded-xl border border-dashed border-[var(--border)] p-6 text-center">
              <p className="text-sm font-semibold text-[var(--text-primary)]">Drop receipts, invoices or scans here</p>
              <p className="mt-1 text-xs text-[var(--text-secondary)]">
                {targetName
                  ? `They'll be filed under ${targetName}.`
                  : "We'll detect the company from each document's TIN and name."}
              </p>
              <button
                type="button"
                onClick={open}
                className="mt-3 inline-flex items-center gap-1.5 rounded-lg bg-[var(--accent)] px-3 py-1.5 text-sm font-medium text-white hover:bg-[var(--accent-hover)]"
              >
                <UploadSimple size={16} /> Upload files
              </button>
            </div>

            {isDragActive && (
              <div className="pointer-events-none absolute inset-0 flex items-center justify-center rounded-xl bg-[var(--accent-subtle)]/80 text-sm font-semibold text-[var(--text-primary)]">
                {targetName ? `Drop to file under ${targetName}` : "Drop to auto-detect the company"}
              </div>
            )}
          </section>
        </div>
      </div>

      {reviewOpen && upload?.status === "awaiting_confirmation" && (
        <UploadReviewDialog
          upload={upload}
          companies={companies}
          canManage={canManage}
          onCompanyCreated={() => {
            loadCompanies().catch(() => undefined);
            loadTree().catch(() => undefined);
          }}
          onConfirm={confirm}
          onClose={() => setReviewOpen(false)}
        />
      )}

      {companyForm && (
        <CompanyForm
          initial={companyForm.initial}
          companyId={companyForm.id}
          onClose={() => setCompanyForm(null)}
          onSaved={companySaved}
        />
      )}

      {openDoc && (
        <DocumentPanel
          doc={openDoc}
          onClose={() => setOpenDoc(null)}
          onChanged={(d) => {
            setOpenDoc(d);
            refreshAfterDocChange();
          }}
          onDeleted={() => {
            setOpenDoc(null);
            refreshAfterDocChange();
          }}
        />
      )}
    </div>
  );
}
```

Note: `CompanyForm` gets a whole `Company` as `initial` when editing; it spreads `EMPTY` and the form fields into the payload, and the backend ignores the extra `id`/`created_at` keys (Pydantic default `extra="ignore"` on `CompanyIn`).

- [ ] **Step 8: Verify**

Run: `cd frontend && npm run lint && npm run build`
Expected: lint clean; build succeeds and lists the `/accounting` route.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/components/accounting frontend/src/app/accounting
git commit -m "feat(accounting): Drive-style intake page, company dialogs, document panel

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: End-to-end verification (manual, real Gemini) + spec note

**Files:**
- None created; the spec doc gets a Phase 1 status line.

- [ ] **Step 1: Bring the stack up and enable the feature in dev**

Run: `docker compose up --build -d && sleep 15 && docker compose logs --tail=30 backend`
Expected: clean startup.
Run: `docker compose exec -T db psql -U snagstock -d snagstock -c "update feature_toggles set enabled=true where key='accounting'"`
Expected: `UPDATE 1`.

- [ ] **Step 2: Walk the flow in the browser** (`http://localhost:3000/accounting`, signed in as an enterprise user). Use 3–5 real sample receipts/invoices (PDF + one phone photo) and check each item:

- [ ] AutoAccounting appears in the sidebar; the page loads with an empty tree.
- [ ] *Add company* → create "Juan's Cloth Trading" with a TIN; it appears in the tree and in the "Drop files for" picker.
- [ ] Picker = Auto-detect, drop the samples → "Detecting companies n/N" → dialog opens; a document addressed to the company's TIN is grouped under it as *certain*; an unknown supplier-only receipt shows as "We couldn't find this company…".
- [ ] *Add to databank* from the dialog pre-fills name/TIN; saving marks the group "Filing to …".
- [ ] *Confirm and file* → "Reading and filing documents" → notice "N files filed"; the tree shows Year → Quarter with counts and an amber review count.
- [ ] Open a quarter → category tiles → a document → page image shows, fields filled, review reasons readable.
- [ ] Edit an amount, *Save* → list updates; *Mark reviewed* → review count drops; *Move* to another quarter → document moves and shows "(moved by hand)"; *Use document date* moves it back.
- [ ] Change a purchase's folder to Expenses + account Office supplies, then drop another invoice from the same supplier with the picker preselected → it lands in Expenses / Office supplies.
- [ ] Drop the exact same file again → notice says "1 already uploaded"; no new document; usage (Enterprise panel) not charged twice.
- [ ] Drop a 0-byte `.pdf` and a renamed `.txt` → red error naming the file; no job starts.
- [ ] Double-click *Confirm and file* quickly → only one extraction runs (one set of documents; backend log shows a single `accounting` job per upload, second request 409).
- [ ] Sign in as an employee of the same firm → can upload and confirm; *Add to databank* is disabled with the tooltip; `PUT /companies` returns 403.
- [ ] Dark mode: tree, tiles, dialogs and amber badges readable.

- [ ] **Step 3: Run the full backend suite once more**

Run: `docker compose exec -T backend python -m pytest -q`
Expected: all pass.

- [ ] **Step 4: Record what's left for production** (do **not** do these without the user's go-ahead — they are infra changes): create a GCS bucket for AutoAccounting with no short lifecycle (≥5-year retention), mount it on `snagstock-backend-{dev,prod}`, set `ACCOUNTING_DIR` to the mount path in `cloudbuild*.yaml`. Until then the upload endpoint returns 503 in production by design, and the toggle stays off.

- [ ] **Step 5: Commit any fixes found during verification**, then report results to the user (what passed, what didn't, with output).
