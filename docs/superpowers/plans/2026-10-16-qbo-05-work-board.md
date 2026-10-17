# QBO 05 — Firm work board, client health, tasks, approve-before-close, notifications

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One firm-wide board of every client's BIR filings (status, assignee, due date, overdue), a health check per
client, free-form tasks, an optional "managers approve filing" setting and a per-user notifications inbox.

**Architecture:** Everything that can be derived is derived on read: filings owed come from `engine.expected_forms`
+ `annual_form` + 1604-C, due dates from `compute/due_dates.py`, status from documents / versions / `filed_forms`.
Only what can't be derived is stored: `aa_work_items` (assignee, status override, manual filed date per
company × period × form), `aa_tasks`, `aa_firm_settings`, `aa_notification_states` (read / dismissed per user and
notification key). Pure logic in `compute/work.py`, `compute/health.py`, `compute/notifications.py`; async glue in
`services/accounting/work.py`; routes in `routers/accounting_work.py`.

**Tech Stack:** FastAPI + SQLAlchemy async, Postgres RLS, Next.js / React / TS.

**Spec:** `2026-10-16-quickbooks-parity-plan.md` §3 "P2 — Firm work board", "P2 — Smaller wins" (Client health
checks, Notifications); catalogue §1 Work, §2 Client overview; program rules in `2026-10-16-qbo-parity-program.md`.

## Global Constraints

- New aa_* tables: `enterprise_id` column, firm RLS policy via `rls._FIRM_TABLES`; every query filters `enterprise_id`.
- Mutations write `audit.record` events (new entities `work_item`, `task`, `firm_settings`).
- Theme CSS vars only, page roots `className="lp ..."`, Hint + guide for the new page, no subheads under headings.
- No email. Pure tests in `backend/tests`, no DB.

## Review Focus

- A company added to the databank today must not show years of "overdue" filings: periods that ended before the
  company was created and have no documents, versions or work item are skipped (`test_old_empty_periods_skipped`).
- Fiscal-year companies (FYE June): withholding forms only when FYE is Mar/Jun/Sep/Dec (engine rule reused), annual due
  on the 15th of the 4th month (`test_fiscal_june_obligations`).
- A form filed through the period (real filing) wins over a manual override; an override never un-files
  (`test_filed_beats_override`).
- An employee with approve-before-close on gets 403 on every "filed" route incl. the board's manual filed mark
  (`test_filing_guard`).
- Notification keys change when the underlying count changes, so a dismissed "3 to review" comes back as "5 to review"
  (`test_review_key_changes_with_count`).

---

### Task 1: Pure work board logic (`compute/work.py`)

**Files:** Create `backend/app/services/accounting/compute/work.py`, `backend/tests/test_aa_work.py`;
modify `compute/due_dates.py` (add `alphalist_due_date(year) -> date`: next business day of Jan 31 of year + 1).

**Produces:**
- `STATUSES = ("no_docs", "docs_in", "needs_review", "generated", "filed")`
- `@dataclass Obligation(form, year, quarter, due)` — quarter 0 = annual return / 1604-C (`form="1604C"`, year = calendar).
- `obligations(facts: CompanyFacts, start: date, end: date, payroll: set[tuple[int,int]], employees_years: set[int]) -> list[Obligation]` — due in [start, end].
- `derive_status(*, filed: bool, generated: bool, documents: int, open_reviews: int, override: str = "") -> str` — filed
  wins; else override if in STATUSES; else generated > needs_review > docs_in > no_docs.
- `form_label(form) -> str` ("0619-E", "1601-C", "2550-Q", "1604-C" …) and `period_text(ob, fye) -> str`
  ("Oct 2026" for monthly forms, "Q4 2026", "FY 2026", "CY 2026").
- `days_left(due, today) -> int`, `is_overdue(status, due, today) -> bool` (not filed and due < today).
- `filter_cards(cards: list[dict], *, company_id=None, status=None, assignee=None) -> list[dict]` (assignee
  "unassigned" matches None).

Tests: Dec-FYE VAT corporation, agent, employees: window Oct 1–Nov 30 2026 gives 0619E-M1 Q4 (Nov 10), 1601C-M1 Q4
(Nov 10), 2550Q Q3 (Oct 26 — 25th is a Sunday), 1702Q Q3 (Nov 30… Nov 29 → next business day), 1601EQ Q3 (Oct 31 → Nov 3
after Nov 1 holiday / weekend); FYE June: no withholding when FYE % 3 != 0 checked with FYE 5; `alphalist_due_date(2026)`
= 2027-02-01 (Jan 31 2027 is Sunday); status table; filters.

### Task 2: Pure health checks (`compute/health.py`)

**Files:** Create `compute/health.py`, `tests/test_aa_health.py`.

**Produces:**
- `negative_balances(balances: dict[str, Decimal], chart: Chart) -> list[dict]` — asset / liability accounts (contra
  excluded) whose balance is on the wrong side; `{code, name, type, balance}` with balance as a positive "wrong way" amount.
- `review_balances(balances, chart) -> list[dict]` — non-zero balances in accounts with system key `vat_difference`
  or a name containing "suspense".
- `months_not_closed(books_start: date | None, closed: set[date], today: date) -> list[date]` — month starts from books
  start through the last full month before today that have no active close.
- `unreconciled_months(line_months: set[tuple[str, date]], reconciled: set[tuple[str, date]], today: date) -> list[tuple[str, date]]` — months that ended before today.
- `reconciled_through(months: list[tuple[date, date]]) -> date | None` (moved from `routers/accounting_bank.py`, which
  then imports it).
- `over_90(items) -> tuple[int, Decimal]` over `subledger.OpenItem` with bucket "90+".

### Task 3: Tables, RLS, settings guard, routes for board / items / settings / people

**Files:** modify `models/accounting.py` (AAWorkItem, AATask, AAFirmSettings, AANotificationState), `rls.py`,
`schema.py` (`ALTER TABLE aa_audit_events ALTER COLUMN company_id DROP NOT NULL`), `audit.py` (entities),
`routers/accounting_scope.py` (`firm_settings(db, ent)`, `require_filing_rights(db, user, ent)`),
`routers/accounting_periods.py` + `accounting_annual.py` (call the guard on the three filed routes);
create `services/accounting/work.py` (board loader), `routers/accounting_work.py`, `schemas/accounting_work.py`;
tests in `test_accounting_rls.py` (new tables), `test_aa_work.py` (guard with stub settings).

Routes: `GET /work/people`, `GET|PUT /work/settings` (PUT owner/admin only), `GET /work/board?start&end&company_id&status&assignee`
(cards + per-company cheap summary), `PUT /work/items` (assignee / override / filed_on; manual "filed" needs the guard).

### Task 4: Company health route + tasks routes

`GET /companies/{id}/health` (reviews by reason, bank accounts with reconciled-through + unreconciled months +
unmatched lines, 2307s pending (light: `cwt_items` without contact merges), months not closed, A/R & A/P > 90, negative
balances and review-account balances from `bank.book_entries(company, today)` when books are on). Tasks CRUD
`GET /tasks`, `POST /tasks`, `PATCH /tasks/{id}`, `DELETE /tasks/{id}` (audited; link checks: company in firm, document
in company).

### Task 5: Notifications (`compute/notifications.py` + routes)

`build(user_id, is_manager, cards, summaries, tasks, today, days) -> list[Notification(key, kind, title, detail, company_id, link, at)]`.
Kinds: `deadline` (unfiled, due ≤ today + days; assignee only, unassigned → everyone), `review` (key has the count),
`bank` (unreconciled months count), `cwt` (2307s pending count), `task_assigned`, `task_due` (due ≤ today + days, not done).
Routes `GET /notifications` (items + unread), `POST /notifications/read` (`keys` or `all`), `POST /notifications/dismiss`.

### Task 6: Frontend

`types/work.ts`, `lib/work-api.ts`, `app/accounting/work/page.tsx` (tabs Filings | Clients | Tasks; filters; overdue
highlight; assignee select; manual filed), `components/work/*` (HealthTile, CompanyHealthPanel, TaskList, TaskForm,
NotificationBell), Sidebar entry "Work" + bell in the rail, FolderTree "Overview" view per company, firm setting toggle
on Team page (owner), filed buttons disabled for employees when the setting is on, tours + hints, audit labels.

### Task 7: Docs + gates

Progress entry, CLAUDE.md layout/gotchas, `npm run build`.

## Decisions

1. **Closing a month was already owner/manager-only** (`_require_manager` on close / reopen / bind). The new firm
   setting "Managers approve filing" therefore adds the guard to *marking returns filed or unfiled* (quarter, per form,
   annual, and the board's manual filed mark). Default off, so behaviour is unchanged until a firm owner turns it on.
2. **Manual "filed" on the board** is stored on the work item only (date + who). It does not post a payment in the books
   and does not credit the annual return: those still need "Mark filed" on a generated version. The card says "Filed
   (marked on the board)".
3. **Status override** may be any board status; a real filing always wins, and an override never hides a filing.
4. **Which cards exist:** cards whose due date falls in the chosen window (default: 90 days back to 45 days ahead).
   Periods that ended before the company was added and have no documents, versions or work item are skipped, so a new
   client doesn't arrive with years of overdue cards.
5. **1604-C** is a card for companies with employees (or employee rows for the year), due Jan 31 (next business day)
   of the next year; status: rows for the year → docs in; only a manual filed mark completes it (we don't store its
   workbook as a version).
6. **Health on the board** shows cheap counts for every client at once (reviews, unmatched bank lines, unreconciled
   months, months not closed); the full check (aging > 90, 2307s, negative / suspense balances, reasons) loads per tile.
7. **2307s pending in health / notifications** use the subledger's pure `cwt_items` without contact merges (no contact
   sync on every poll); the Customers page stays the authoritative list.
8. **Notifications:** deadlines go to the card's assignee, or to everyone in the firm when unassigned; review / bank /
   2307 items go to everyone; task items go to the assignee. The key carries the count (or due date), so a changed
   situation comes back after a dismiss. Window = firm setting "deadline days", default 7. Bell polls every 2 minutes.
9. **Audit events without a company** (firm settings, a task with no company) are allowed:
   `aa_audit_events.company_id` becomes nullable. They don't appear on any company's Audit log.
10. **Tasks** are visible to the whole firm; anyone in the firm may create / edit / complete them (it's a shared to-do
    list); deleting is limited to the creator, owners and managers.
