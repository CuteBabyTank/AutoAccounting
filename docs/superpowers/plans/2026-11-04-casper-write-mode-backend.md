# Casper write mode backend implementation plan

**Goal:** Implement the approved Casper proposal/confirm/undo backend, preserving the frontend contract.
**Architecture:** Pure policy functions own limits and lifecycle decisions. A firm-scoped action service resolves immutable proposals and calls existing route handlers inside a savepoint-bound session, retaining the outer action and firm locks across their commits. SSE tools only create proposals.
**Stack:** Existing FastAPI, SQLAlchemy async/Postgres, Pydantic, pytest.
**Spec:** docs/superpowers/specs/2026-11-04-casper-write-mode-design.md

## Constraints

No frontend edits, no commits. Same-user confirmation, 15-minute expiry, 7-day undo, max 3 proposals/turn, Manila daily caps 40 changes/person, 10 deletes/person, 30 deletes/firm. FORCE RLS and explicit firm filters. Existing read-only prompt remains identical. Tests require no DB/Gemini.

## Review focus

Concurrent confirmations/caps retain locks through route commits; foreign and ambiguous identifiers fail closed; document route supplier-rule propagation cannot turn one proposal into bulk edits; edited/deleted/restored targets refuse stale undo; undo restores exact task identifiers and period metadata.

## Tasks

- [x] Add failing policy/contract tests for lifecycle boundaries, caps, Manila dates, unchanged fields, registry/declarations, permissions, audit tagging, and SSE proposal ordering/limits.
- [x] Implement pure action policy, model/RLS/additive migration, settings and audit context.
- [x] Implement action registry: scoped resolution, allowlisted validation and previews, route-based apply/undo, restoration guards and lazy purge. Translate spec task/filing statuses to existing route statuses. Add document notes support, since the current document model has no notes column. Keep Casper document edits single-record by suppressing supplier-rule learning/propagation during confirmed Casper execution.
- [x] Add action routes and feature enforcement, write tools, conditional prompt and SSE emission.
- [x] Run local py_compile on all changed Python files and targeted pure pytest if installed. Review backend diff and document results. Docker, the full suite, ruff and live smoke are reserved for the coordinator per the implementation request.

Local verification: all changed/new Python files compile. Targeted pytest is skipped because pytest is absent from both local Python installations. Docker, live smoke, full suite and ruff were not run, per request.
