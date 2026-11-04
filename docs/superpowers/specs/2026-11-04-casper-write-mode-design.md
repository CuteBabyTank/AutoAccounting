# Casper write mode: design

## Intent

Firm staff want to tell Casper to do routine things (make a task, assign it, tick it done, fix a document's
account, delete a junk upload) instead of clicking through the app. A small model reading untrusted documents
must never be able to do real damage on its own: no mass deletes, nothing firm-wide, nothing irreversible, and any
delete by Casper is restorable for 7 days.

## Core rule: Casper proposes, a person confirms

The model never writes. Write tools only create a **proposal** row (`aa_assistant_actions`, status `proposed`)
with the exact, server-resolved change and a human-readable preview. The chat shows a card; only the person's own
click on **Confirm** (a plain HTTP route, no model involved) runs it. Prompt injection inside a document can at
worst produce a proposal card the person can see and cancel.

## Goals / non-goals / anti-goals

- Goals: a small allowlist of single-record changes; every change audited as done by Casper; every Casper change
  undoable for 7 days (deletes restorable, edits revertible if untouched since).
- Non-goals (v1): bulk changes, companies, contacts, journal entries, bank matches, imports, returns, closing.
- Anti-goals: Casper can delete or change a firm, a company, a person, a role, a setting, a filed return or a
  closed month; Casper acts without a click; a confirm runs different args than the card showed; a Casper action
  bypasses the permission or retention checks the normal screen has.

## Allowed actions (the whole list)

| kind | what | runs through | undo (7 days) |
|---|---|---|---|
| `create_task` | new task (title, notes, due date, priority, company, document, assignee) | `accounting_tasks.create_task` | delete the task (only if unchanged since) |
| `update_task` | title, notes, due date, priority, status (todo / in_progress / done), assignee | `accounting_tasks.update_task` | patch back to the before snapshot if unchanged since |
| `delete_task` | delete one task | own: snapshot kept in the action, then the route's delete | re-insert with the same id and fields |
| `update_document` | `gl_account_code`, `category`, `period_year`/`period_quarter`, `notes` only | `accounting.patch_document` | patch back if unchanged since |
| `delete_document` | delete one document (owner/manager only) | `accounting.delete_document` (soft delete, retention guards) | clear `deleted_at` under `protect_history` for its dates/period, then relink, rematch, duplicate refresh |
| `assign_filing` | set a board filing's assignee or status (`todo`/`in_progress`/`ready`, never `filed`) | `accounting_work` PUT `/work/items` handler | put back the previous assignee/status |

Anything not in this table has no tool. In particular there is no tool that touches firms, companies, users,
team, roles, firm settings, features, billing, returns/filing, books close, bank, JEs, contacts or imports.

## Guardrails

1. **Confirm gate**: proposals run only via `POST /assistant/actions/{id}/confirm` by the same user who asked, in
   the same firm, within 15 minutes, once (row lock + status `proposed` → `applied`/`failed`). Confirm takes no
   body: the stored, server-resolved args run, exactly what the card shows.
2. **Re-check at confirm**: execution calls the same route handler the screens use with the person's own `User`,
   so role checks, firm scope, `lock_firm`, retention (`deletion.protect_document`) and audit all apply as if they
   clicked it themselves. Errors become `failed` with the route's message.
3. **Who may use it**: `aa_firm_settings.assistant_writes` = `off` | `managers` (default) | `everyone`; owners
   change it on the Work settings card. Platform kill switch: feature `assistant_write` (Features page). Write
   mode is also a per-chat toggle in the dock, **off by default**; with it off (or not allowed) the model is not
   even offered write tools.
4. **One record per proposal, few per turn**: at most 3 proposals per turn (more → the tool returns an error asking
   the model to stop and tell the person to do bulk work on the screen). Ids must resolve to one record; names
   resolve like the read tools (ambiguous → error listing matches).
5. **Daily caps** (per Manila day, counted from applied actions): 40 applied changes per person, 10 deletes per
   person, 30 deletes per firm. Over cap, proposing returns an error and confirm returns 429.
6. **Destructive marking**: delete cards are red, say "Can be restored for 7 days", and name the record
   (document label / task title, company).
7. **Audit**: every write keeps the route's own audit event with `reason="Casper (confirmed by <name>)"` via a
   context variable read by `audit.record` when no reason is given; undo/restore are audited the same way
   (`restore` action for deletes).
8. **Isolation**: proposal lookups reuse `tools.resolve_company` and firm-scoped queries (`assistant/scope.py`);
   actions table has FORCE RLS like every aa_* table; foreign ids get the same not-found as missing ids.

## 7-day cooling period

Every applied action stores `undo_until = applied_at + 7 days` and what undo needs (`undo_data`: before snapshot,
or the deleted task's full row). Until then **Undo / Restore** shows on the chat card and in "Casper's changes"
(dock). After 7 days, undo is refused (`410`), and `undo_data` for deleted tasks is cleared lazily when actions
are listed (the task is then gone, as a normal delete). Deleted documents stay soft-deleted as today (tax
retention), only the restore button goes away. Undo refuses (409) if the record changed after Casper's change, if
restoring would touch a closed month / filed quarter, or a deleted document's file has since been re-uploaded and
kept as another document (duplicate sha).

## Data

`aa_assistant_actions`: `id`, `enterprise_id`, `user_id`, `company_id` (null for firm-level), `kind`, `args`
(JSONB, resolved ids), `summary` (one line), `details` (JSONB list of `{label, value}`), `destructive` (bool),
`status` (`proposed|applied|failed|cancelled|expired|undone`), `error`, `target_id` (uuid), `undo_data` (JSONB),
`created_at`, `expires_at`, `applied_at`, `undo_until`, `undone_at`, `undone_by`. FORCE RLS keyed to the firm
(same policy shape as `aa_assistant_usage`). Add to `schema.py` / startup migrations, `audit.ENTITIES` not needed
(the underlying entity is audited).

`aa_firm_settings.assistant_writes` text default `managers`.

## API (frontend contract)

- `POST /api/accounting/assistant/chat` body gains `write: bool` (default false).
- New SSE event: `{"type": "proposal", "action": ActionOut}` emitted right after the tool's observation. The model
  is told "Proposed; the person must press Confirm" and should say so in its answer.
- `ActionOut = {id, kind, summary, details: [{label, value}], destructive, status, error, company_name,
  created_at, expires_at, applied_at, undo_until, undone_at, can_confirm, can_undo, user_name}`.
- `POST /assistant/actions/{id}/confirm` → ActionOut (409 if not `proposed` or expired, 429 over caps,
  the route's status on failure with `failed` stored).
- `POST /assistant/actions/{id}/cancel` → ActionOut.
- `POST /assistant/actions/{id}/undo` → ActionOut (410 past 7 days, 409 changed since / retention).
- `GET /assistant/actions` → `ActionOut[]`, last 7 days, newest first; own actions, owners/managers see the firm's.
- `GET /assistant/info` gains `write: {allowed: bool, reason: string}` (reason when not allowed: off for the firm,
  managers only, switched off by platform).
- Feature routes: `/assistant/actions…` under feature `assistant_write` (and `assistant`).

## UI

- Dock header: a "Write mode" switch (off each time the dock opens; hidden when `info.write.allowed` is false).
  While on, a thin amber strip: "Casper can propose changes. Nothing happens until you confirm."
- Proposal card in the conversation: summary, details list, Confirm / Cancel; red outline + "Can be restored for
  7 days" when destructive. After confirm: "Done" + Undo (or Restore) with time left; failed shows the error.
- "Casper's changes" link in the dock opens a list (GET /assistant/actions) with status and Undo/Restore.
- Owner's Work settings card: "Casper can make changes: Off / Managers and owner / Everyone".

## Calls made without the person (all mine)

Confirmation for every write; write mode off by default per chat; managers-only default; document deletes
owner/manager only; 3 proposals/turn, 40 changes, 10 deletes per person and 30 deletes per firm per day; 15-minute
proposal expiry; "filed" never settable by Casper.
