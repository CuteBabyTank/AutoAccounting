# AutoAccounting — Claude Code Guide

AI back office for Philippine accounting firms: drop client receipts/invoices/2307s/payroll → Gemini extracts and sorts them into a per-firm company databank, filed Company → Year → Quarter → BIR returns (2550-Q, 2551-Q, 1701-Q/1702-Q, 0619-E, 1601-EQ/C, annual 1701/1701-A/1702-RT, 1604-C alphalist + 2316s, outgoing 2307s) as filled PDFs + versioned XLSX, and BIR loose-leaf books of accounts (journals, GL, TB, closing entries, financial statements, month close). Multi-tenant: `admin` = platform owner, `enterprise` = firm owner, `manager`, `employee`, `unverified`. Auth is **Google SSO only**.

Extracted from the SnagStock repo's `AutoAccounting` branch (2026-10-15). The branch there is kept as history; this repo is now the source of truth.

## Repo layout

The **static marketing site** lives in `frontend/public/` (`index.html`, `styles.css`, `app.js`, `assets/`; product notes in root `PRODUCT.md`): plain HTML/CSS/JS with no build step. `next.config.ts` serves it at `/homepage` (a rewrite) and redirects `/` there, so it is the app's default page. Every AutoAccounting logo and sign-out lead to `/homepage` (`HOMEPAGE` in `lib/roles.ts`; use a plain `<a>`, not `next/link`, since it isn't a Next route). "Log in" goes to `/login`; the "Book a demo" CTAs open an email to the contact address (no booking tool yet). Copy rule: no subheads under section headings; if one is unavoidable, one sentence. Changes to `next.config.ts` need `docker compose restart frontend`.

```
backend/app/
  main.py               # FastAPI app, middleware, routers (auth, team, admin, accounting)
  startup_migrations.py # create_all → aa_* additive columns → RLS (idempotent, runs in lifespan)
  config.py             # pydantic-settings, validate_secrets_at_startup()
  database.py           # async engine; pooler auto-detect (6543 = transaction) + SSL context
  dependencies.py       # get_db, get_current_user (binds RLS user), role guards, EnterpriseContext
  auth/                 # jwt.py (HS256, 8h), security.py (in-memory RateLimiters)
  forms/                # BIR comb-cell overlay layouts (overlay.py + bir*_layout.py) + templates/*.pdf
  models/               # user, api_usage, accounting (all aa_* tables)
  routers/              # auth, team (firm staff), admin (platform owner), accounting*.py
  services/
    accounting/         # bank_statement (parse + tie-out), bank_match (matcher, rules), bank_report_pdf,
                        # books/bank.py (store/rematch/reconcile glue), compute/bank_books + bank_reconcile;
                        # contacts (customer/supplier master), books/subledger.py + compute/subledger
                        # (A/R, A/P open items, aging, 2307s), subledger_report (aging XLSX/PDF, statement);
                        # work.py (work board loader) + compute/work, health, notifications, tasks;
                        # reports.py (live report loader) + compute/reports, report_export (XLSX/PDF),
                        # report_pack (management pack PDF + DOCX via zipfile);
                        # pipeline, extraction, matching, classify, periods, tree, storage, pdf_*,
                        # render_xlsx, filing, rls, schema; compute/ (tax engine); books/
    gemini_service.py   # rate limiters + prompt cache + _call_gemini + PDF page rendering
    usage_service.py    # monthly page counts + budget debits (charge_for_pages)
    form_filler_service.py  # BIR 2307 PDF fill (outgoing 2307s)
    file_service.py, spreadsheet_safe.py, atc_codes.py, budget_service.py, auth_service.py
  ocr/__init__.py       # clean_tin/date/amount/text/atc/zip
backend/tests/          # pure-logic + router-isolation tests (no DB, no Gemini)

frontend/src/
  app/{login,pending,accounting,accounting/companies,accounting/work,team,admin}/page.tsx
  app/providers.tsx     # Theme + Auth + AuthGate (role routing from lib/roles.ts)
  components/accounting/  # all accounting UI panels
  components/work/      # work board pieces: CompanyHealth, TaskList/TaskForm, NotificationBell, FirmSettingsCard
  components/layout/    # Sidebar, AppFlow (shared page background)
  lib/{api,auth,roles,accounting-api,accounting-format}.ts(x)
  types/{index,accounting}.ts
  middleware.ts         # per-request nonce CSP

docs/superpowers/{specs,plans}/  # design specs + phase plans (written while in SnagStock)
```

## Commands

```bash
cp .env.example .env            # fill GEMINI_API_KEY, NEXT_PUBLIC_GOOGLE_CLIENT_ID, BOOTSTRAP_ADMIN_EMAIL
docker compose up --build -d    # db :5433, backend :8001, frontend :3001
docker compose logs -f backend

# Backend tests + lint (inside the container; no local pip)
docker compose exec backend python -m pytest -q
docker compose exec backend ruff check app --select F,E9

# Frontend
cd frontend && npm install && npm run lint && npx tsc --noEmit && npm run build
```

Both `backend/` and `frontend/` are bind-mounted and hot-reload (frontend uses `WATCHPACK_POLLING`; `node_modules`/`.next` stay in anonymous volumes). Rebuild only after dependency changes (`docker compose up --build -d --renew-anon-volumes`) or `.env` changes (`--force-recreate`).

## First run

1. Set `BOOTSTRAP_ADMIN_EMAIL` and sign in with that Google account. It becomes the platform admin, but only while no admin exists.
2. Other people sign in once (they land on `/pending` as unverified). On **Platform admin**, click "Make firm" to turn someone into a firm owner.
3. The firm owner adds staff by email on **Team** and promotes managers there.
4. **Without Google set up:** with `ENVIRONMENT=development` and `ENABLE_DEV_LOGIN=true`, `/login` shows a stand-in "Sign in with Google" button that signs straight in as the platform admin (creating one on a fresh DB) via `POST /api/auth/dev-login`. It disappears once `NEXT_PUBLIC_GOOGLE_CLIENT_ID` is set, and the backend refuses to start with `ENABLE_DEV_LOGIN` outside development.
5. Billing is opt-in. With no page rate set, uploads are free and never blocked. Once a rate is set on Platform admin, each extracted page debits the firm's budget and uploads stop at ₱0.

## Env vars

Required in production: `GEMINI_API_KEY`, `JWT_SECRET` (≥32 chars), `GOOGLE_CLIENT_ID`; insecure defaults fail startup. Also: `DATABASE_URL`, `ENVIRONMENT`, `FRONTEND_URL` (comma-separated CORS origins), `ACCOUNTING_GEMINI_MODEL`, `ACCOUNTING_GEMINI_THINKING_LEVEL`, `ACCOUNTING_DIR`, `MAX_FILE_SIZE_MB`, `MAX_BATCH_SIZE`, `BOOTSTRAP_ADMIN_EMAIL`, `ENABLE_DEV_LOGIN`, `JWT_SECRET_PREVIOUS`, `DATABASE_SSL_MODE`, `DATABASE_SSL_ROOT_CERT`, `DATABASE_POOLER`, Gemini rate-limit knobs. Frontend: `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_GOOGLE_CLIENT_ID`.

## Gotchas

- **aa_* tables have FORCE RLS** keyed on `app.current_user_id` → the user's firm. Every DB session that touches them must `bind_session_user` (`get_current_user` does it; background jobs like `pipeline.run_extraction` do it themselves). The app's DB role must be **NOBYPASSRLS** or RLS silently does nothing.
- **Firm scope:** every accounting row carries `enterprise_id` = the firm owner's user id (`routers/accounting_scope.scope_for`). Always filter by it, even with RLS on.
- **Storage:** documents go to `ACCOUNTING_DIR` (falls back to `backend/uploads/` in dev, gitignored). Tax records must be kept ≥5 years, so prod needs a long-retention volume. In production the upload endpoint returns 503 until `ACCOUNTING_DIR` is set.
- **Schema changes:** add aa_* columns to the model *and* `services/accounting/schema.py` (for existing DBs). Destructive changes go in `alembic/` (empty so far; `start.sh` runs `alembic upgrade head`).
- **Transaction pooler (port 6543):** statement caches are off. No session state across transactions (`SET LOCAL`/`set_config(..., true)` only), no advisory locks, temp tables or LISTEN/NOTIFY.
- **CORS middleware must be added LAST** in `main.py` so it wraps everything and answers preflight.
- **Abuse middleware** blocks empty User-Agent always and bot UAs (`curl`, `python-requests`…) in prod; skips `/api/health` + `OPTIONS`.
- **In-memory rate limiters** are per instance; N instances ≈ N× the limit.
- **Bank statements:** `kind == "statement"` docs stay category `support`; their lines live in `aa_bank_statements` / `aa_bank_lines` (stored by `books/bank.store_statement` in the pipeline, then `bank.rematch`). A line only posts when `match_status` is `matched` (auto: one strong candidate, partial with payee + number, or a cash-deposit transfer) or `confirmed`, and its statement has an `account_code` (resolved by the last 4 digits of `aa_accounts.bank_account_no`). A document match **replaces** the doc's `paid_on` payment (`compute/bank_books.apply_bank_lines`); never add another payment path for bank-matched docs. Amount alone never auto-links. Anything that changes a line must `void_reconciliations` + `rematch` + `touch_books`. Lines keep the file page they are printed on (`aa_bank_lines.page`, via `bank_statement.file_page`; None for
  older extractions). Closing a month with unreconciled statement lines needs `override_reason` (409 `bank_unreconciled:` otherwise). `aa_companies.review_flags.opening_balance_missing` is refreshed by `bank.refresh_opening_flag`.
- **Audit log:** every router that changes firm data calls `services/accounting/audit.record(db, ent=, company_id=, user=, entity=, entity_id=, action=, before=, after=, reason=, label=)` before its commit (snapshot the row with `audit.snapshot(row, fields)` before mutating; only changed fields are stored, a no-op writes nothing; pass `before=None` for creates, `after=None` for deletes). New entities go in `audit.ENTITIES` and `ENTITY_LABELS`/`ACTION_LABELS` in `components/accounting/AuditTrail.tsx`. `aa_audit_events` is append-only (RLS has SELECT + INSERT policies only). Read via `GET /api/accounting/audit-events`. The dev DB role is a superuser, so RLS is not enforced locally; test policies with a NOBYPASSRLS role.
- **Review reasons:** set `needs_review` with `review_rules.needs_review_for(reasons)`, never `bool(reasons)`: soft reasons (`payment_unverified`) show but don't queue or block close. Per-reason details go in `aa_documents.review_notes`. Payment flags (`payment_source_unknown`, `payment_unverified`) are cleared by `review_rules.sync_payment_flags(docs, paid_ids)` (called from `relink_receipts`); bank matching passes its matched document ids as `paid_ids`. A VAT mismatch claims 12% and posts the excess to `vat_difference` (1310); documents stored before that rule are
  switched by `books/vat_backfill.backfill_vat_difference` (run from `load_periods`, idempotent, audited as a system
  event), except in filed quarters, which keep the disallowed VAT and get `review_notes.vat_math_mismatch.legacy`.
- **Work board (`routers/accounting_work.py`, `accounting_tasks.py`):** filings owed, their due dates and status are
  derived on read (`compute/work.obligations` reuses `engine.expected_forms`, `annual_form`, `due_dates`); only the
  assignee, a status override and a board "filed" date live in `aa_work_items`. A board filing does **not** post a
  payment or credit the annual return (only "Mark filed" on a version does). Notifications are derived on read
  (`compute/notifications.build`, incl. recurring entries due); `aa_notification_states` only keeps read / dismissed
  per person and key, and keys carry the count or date so a changed situation reappears. The board loads only the
  fiscal years in `compute/work.year_bounds(start, end)`. `aa_firm_settings.approve_before_close` gates every
  "filed" route through `accounting_scope.require_filing_rights` — add it to any new route that marks a return
  filed. Firm-level audit events (settings, tasks without a company) have `company_id` NULL.
- **Subledgers (A/R, A/P):** `aa_contacts` is synced from documents on read (`books/subledger.load_subledger`), keyed
  by TIN else normalized name; merges follow `merged_into_id` (`contacts.resolve`). Open items use the books' own
  payments (`document_payments` + `apply_bank_lines`), so add new payment sources there, not in the subledger.
  Default account / ATC per supplier live only in `aa_supplier_rules`. Contact edits / merges must call `audit.record`.
  Resolve payment amounts with `compute/subledger.payment_amounts` (as the books do: a write-off never shrinks a later
  open-ended payment, so money received after a write-off is a credit on the customer + a health issue, never an
  auto recovery JE). The live aging ends with a tie to the books' control (`control_tie`): CWT still in A/R and
  counter-paid documents are by-design differences.
- **Live reports (`routers/accounting_reports.py`):** every report is reshaped from `books.bank.book_entries` by pure
  `compute/reports.py` (accrual only). Closing entries (`close:*`, `fix:close:*`) are left out; earlier fiscal years'
  P&L shows as "Prior years' earnings not yet closed". Report windows go through `reports.check_window` (2000-01-01 to
  the end of next fiscal year, ≤ 10 years) — keep any new report route behind it, since the engine's work grows with
  the date. An engine `ValueError` becomes an Invalid Journal Transactions row and a 409 elsewhere. Drill-down maps
  entry ids to sources in `compute/reports.entry_ref` — add a branch there when the engine gets a new id prefix.
  Adjusting entries = JEs with `is_adjusting` + `depreciation` / `inventory` sources. The management pack is saved
  in the quarter's output folder; latest paths on `aa_periods.pack_files`, notes in `pack_notes`.
- **Spreadsheet output:** run every untrusted cell through `spreadsheet_safe.csv_safe` (formula injection).
- **Reclassify / locks / templates (QBO 07):** reclassify (`routers/accounting_reclassify.py`, pure
  `compute/reclassify.py`) only changes classification (a document's `gl_account_code` / `ewt_atc`, typed JE line
  accounts), never generated postings; closed months correct themselves through `book_close.apply_closes`.
  `aa_accounts.locked` blocks new postings by people (400 via `books.chart.locked_message`) and extraction (review
  reason `account_locked`); engine-only system accounts can't be locked. Chart templates: built-ins in
  `books/templates.py`, firm ones in `aa_coa_templates`; `coa_template` on company create.
- **Imports (QBO 08):** `routers/accounting_imports.py` (stateless preview → confirm; the confirm re-parses the file),
  pure `importing.py` (amounts, date detection, fuzzy account match) + `import_rows.py` (TB / open items / JE
  builders); sheets read by `payroll_import.parse_sheet`. The opening TB writes the single `kind="opening"` JE; imported
  JEs go through `accounting_books.entry_problem` (shared with the JE form). Opening open items live in
  `aa_opening_items` and enter the engine via `opening_items.opening_doc_line` (dated the day before `books_start`,
  so only their payments post — never give them a document entry or the opening A/R / A/P doubles); anything that
  loads documents for open items / payments (loader, subledger, bank candidates) must add them too.
  **Undo:** every confirm writes an `aa_import_batches` row and tags what it wrote with `import_batch_id` (JEs, opening
  items); `written` keeps each row's `import_undo.fingerprint`, and the opening TB batch keeps the opening entry it
  replaced in `restore` (`{"opening": null}` if none). `POST /import-batches/{id}/undo` (managers) soft-deletes the
  batch's rows or restores the prior opening entry under the company row lock, refusing (409, `import_undo.undo_problem`)
  for closed months, filed quarters / annual returns, live bank reconciliations, confirmed bank matches, payments,
  write-offs and edits. A new import kind, or anything else that writes rows from an import, must tag them and keep
  fingerprints; a new way for later work to depend on imported rows needs a guard in `UndoFacts`. Imports before
  2026-10-19 have no batch and can't be undone.
- **PDF templates** are calibrated comb-cell layouts (`forms/overlay.py`); re-calibrate when BIR revises a form.
- **Global search** (`routers/accounting_search.py`, parser `services/accounting/search.py`): one firm-scoped SELECT per group; add a new searchable table there (and its index to `schema.search_index_statements`, pg_trgm GIN only when the extension exists). Results open through `lib/search-nav.ts`: `/accounting?company=&view=&year=&quarter=&account=&month=&contact=&doc=` is parsed by `parseTarget` (UUIDs via `safeId`, shapes checked); on `/accounting` it's the `aa:open-target` event instead of a reload. The palette (`components/search/SearchPalette.tsx`, "/" or Cmd/Ctrl-K) lives in the Sidebar.
- **Recurring entries / write-offs / checklists** (`routers/accounting_recurring.py`, `accounting_writeoff.py`, `accounting_checklists.py`; pure logic in `compute/recurring.py`, `writeoff.py`, `checklists.py`): recurring templates never post on their own (no scheduler; "Post due entries" is a user action, row-locked, one JE per template per date via `aa_journal_entries.recurring_id`). A write-off is one JE whose `writeoff_items` the subledger reads back as payments (`books/subledger.writeoff_rows`), so it can't be edited, only deleted (which reopens the invoices). Anything new that computes A/R open balances must include those payments. Frontend calls for these and the cash forecast live in `lib/extras-api.ts` / `types/extras.ts`.
- **Privacy toggle** (`lib/privacy.ts`, `PrivacyToggle`): give any dashboard amount the class `aa-amount` and it blurs while "Hide amounts" is on.
- **Notification jumps:** a bell click opens its target (`NotificationBell.target`) and rings the element marked `data-focus` for ~2 s (`lib/focus.ts` `flashFocus`, names from `focusName`; CSS `.aa-focus-flash`). A new notification kind needs a branch in `target` and a `data-focus` on what it points at.
- **Tailwind `dark:`** follows the OS here; use the theme CSS vars instead.
- **Frontend token** lives in `sessionStorage` (`autoaccounting_token`). The axios interceptor attaches it, and on 401 it is cleared and AuthGate redirects.

## Open items carried over

Alphalist DAT export (BIR layout unverified), Gemini read of scanned payroll registers, 1604-E, 1702-RT balance sheet not yet defaulted from books, manual contribution remittances, WC010 vs WC011 manual, whether IEIRD landed cost feeds COGS (ask CPA). Deploy pipeline not set up yet (`Dockerfile.prod` files exist for both apps).

## Conventions

- Python: type hints, `Mapped[...]`, `X | None`; routers raise `HTTPException`, services raise `ValueError`.
- Logging: structured key=value; auth events → `auth.audit`, Gemini → `gemini`.
- Frontend: strict TS, `@/*` → `src/*`, page-scoped `useState`; accounting UI lives under `components/accounting`.
- App background: every page shares `components/layout/AppFlow` (the homepage line ribbons in the right gutter + a slow emerald glow). AuthGate mounts it once inside `<main>`, so new signed-in pages get it automatically: give the page root `className="lp ..."` and no background of its own (nested `.lp` roots are transparent). Public pages outside the shell (login, pending) render `<AppFlow />` in their own `.lp` root. No grid or blob backdrops.
