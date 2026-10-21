# Task tracker implementation plan

Goal: implement the user's decided design A–E from this session, without commits or Docker.

Architecture: keep assignment and history decisions pure in compute/; firm-scoped async services load data and serialize assignment writes using a firm owner row lock. Existing audit events provide assignment recency and filing actors. Additive columns run through schema.py at startup.

## Tasks

- [x] 1. Backend assignment: pure deterministic planner and tests; handler, auto_assign, assigned_auto columns; company handler route; auto-assignment service/route; task-create integration and audited manual edits.
- [x] 2. Backend tracker: completed_by transitions and tests; pure history aggregation and employee scoping; firm-scoped history loader/route; audit-derived backfill; isolation tests; feature registry and CLAUDE.md.
- [x] 3. Frontend (independent ownership: frontend files only): extend work types/API; handler controls and confirmation; auto-assign results; History filters/summary/pagination; task audit timeline; settings toggle; tour stop. Run TypeScript and ESLint.
- [x] 4. Review combined change against A–E, run available pure tests/static checks, inspect diff; report changed files, startup migration/backfill commands and hand checks.

## Shared API contracts

Existing board company summaries gain handler_id: string|null and unassigned_open_items: number (open tasks in board window, including undated tasks, + not-filed filings). WorkCard and Task gain assigned_auto: boolean; Task gains completed_by and completed_by_name. FirmSettings gains auto_assign and can_auto_assign (managers/owner/admin); can_edit retains owner-only approval/deadline permissions.

PUT /work/companies/{company_id}/handler body {handler_id: UUID|null} -> {handler_id}; managers/owner/admin only. Does not assign anything itself.
POST /work/auto-assign query start/end/company_id (like board) -> {total: number, people: [{id,name,count}]}. Managers/owner/admin only. Off setting yields total 0.
GET /work/history query from/to (inclusive ISO dates), person/company UUID, kind task|filing, limit<=200, offset -> {items:[{id,kind,title,company_id,company_name,completed_by,completed_by_name,completed_at,assignee_id,assignee_name,due_date,on_time:boolean|null,source}],summary:[{person_id:string|null,person_name,completed,on_time,late,open_now}],total,limit,offset}. Employees forced to their own actor id. Unspecified due date yields null on_time. All dates Manila calendar days. History filter company/person/kind applies consistently to summaries and open counts, pagination applies only to items.
Timeline reuses accountingApi.auditEvents (entity=task, entity_id=task.id); no new notification kind.

## Review focus

- Concurrent auto/manual writes must preserve manual choices and avoid duplicate assignment audits.
- Foreign company/person ids must not reveal another firm's rows.
- Date windows must be bounded before derived filing work; fiscal year bounds reused.
- Version filing actor must come from audit evidence, never output creator or assignee; unknown remains Unknown.
- Task form edits unrelated to assignment must preserve the Auto flag; reopening clears completion metadata.

Rulings: task windows include undated tasks, so general firm tasks remain assignable. Assignment name ties use id as final stable tie. A board mark and version filing are separate completions with source labels. No optional company-form handler control (Clients tab provides required control).


## Verification

- TypeScript (`npx tsc --noEmit`) and ESLint (`npx eslint src`) pass.
- Python 3.12 compilation and git diff whitespace checks pass.
- 25 dependency-free new/existing work/assignment/history/task test functions pass using an assertion runner. Local Python has no pytest/backend dependencies; the full backend suite and fake-DB router tests must run in the user's container.
- Independent static review checked firm isolation, SQLAlchemy query shapes, actors, locks and frontend contracts. Fixed a concurrent member-removal race by locking eligible user rows; real filing mutations also take the firm lock.
- Open now includes all open tasks and not-filed filings in the default board window. Filing dates display without invented times. Former staff from history summaries remain available as person filters.

## Apply and exercise

Restart the backend to run startup additive schema changes. Run `python -m app.services.accounting.books.task_completed_by --dry-run`, then without `--dry-run` inside the backend container. Run `docker compose exec backend python -m pytest -q`.

Hand checks: handler confirmation yes/no; auto-assign default/off, repeat and concurrent clicks; manual assignments preserved; edit notes retains Auto; completion/reopen actor; board and return-version completions, including Unknown; History filters/pagination and employee scope; Work tour and notification focus.

## Files changed

- `CLAUDE.md`
- `backend/app/models/accounting.py`
- `backend/app/routers/accounting_scope.py`
- `backend/app/routers/accounting_tasks.py`
- `backend/app/routers/accounting_work.py`
- `backend/app/schemas/accounting_work.py`
- `backend/app/services/accounting/assignment.py`
- `backend/app/services/accounting/books/task_completed_by.py`
- `backend/app/services/accounting/compute/assign.py`
- `backend/app/services/accounting/compute/tasks.py`
- `backend/app/services/accounting/compute/work.py`
- `backend/app/services/accounting/compute/work_history.py`
- `backend/app/services/accounting/schema.py`
- `backend/app/services/accounting/work.py`
- `backend/app/services/accounting/work_history.py`
- `backend/app/services/features.py`
- `backend/tests/test_aa_assign.py`
- `backend/tests/test_aa_tracker_routes.py`
- `backend/tests/test_aa_work_history.py`
- `docs/superpowers/plans/2026-10-21-task-tracker.md`
- `frontend/src/app/accounting/work/page.tsx`
- `frontend/src/components/accounting/AuditTrail.tsx`
- `frontend/src/components/guide/tours/spots.ts`
- `frontend/src/components/work/FirmSettingsCard.tsx`
- `frontend/src/components/work/TaskForm.tsx`
- `frontend/src/components/work/TaskHistory.tsx`
- `frontend/src/components/work/TaskList.tsx`
- `frontend/src/components/work/WorkHistory.tsx`
- `frontend/src/components/work/ui.tsx`
- `frontend/src/lib/work-api.ts`
- `frontend/src/types/work.ts`
