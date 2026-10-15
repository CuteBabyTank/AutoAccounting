# AutoAccounting — Claude Code Guide

AI back office for Philippine accounting firms: drop client receipts/invoices/2307s/payroll → Gemini extracts and sorts them into a per-firm company databank, filed Company → Year → Quarter → BIR returns (2550-Q, 2551-Q, 1701-Q/1702-Q, 0619-E, 1601-EQ/C, annual 1701/1701-A/1702-RT, 1604-C alphalist + 2316s, outgoing 2307s) as filled PDFs + versioned XLSX, and BIR loose-leaf books of accounts (journals, GL, TB, closing entries, financial statements, month close). Multi-tenant: `admin` = platform owner, `enterprise` = firm owner, `manager`, `employee`, `unverified`. Auth is **Google SSO only**.

Extracted from the SnagStock repo's `AutoAccounting` branch (2026-10-15). The branch there is kept as history; this repo is now the source of truth.

## Repo layout

The repo root also holds the **static marketing site** (`index.html`, `styles.css`, `app.js`, `assets/`, `PRODUCT.md`): plain HTML/CSS/JS with no build step. It is separate from the app below.

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
    accounting/         # pipeline, extraction, matching, classify, periods, tree, storage, pdf_*,
                        # render_xlsx, filing, rls, schema; compute/ (tax engine); books/
    gemini_service.py   # rate limiters + prompt cache + _call_gemini + PDF page rendering
    usage_service.py    # monthly page counts + budget debits (charge_for_pages)
    form_filler_service.py  # BIR 2307 PDF fill (outgoing 2307s)
    file_service.py, spreadsheet_safe.py, atc_codes.py, budget_service.py, auth_service.py
  ocr/__init__.py       # clean_tin/date/amount/text/atc/zip
backend/tests/          # pure-logic + router-isolation tests (no DB, no Gemini)

frontend/src/
  app/{login,pending,accounting,accounting/companies,team,admin}/page.tsx
  app/providers.tsx     # Theme + Auth + AuthGate (role routing from lib/roles.ts)
  components/accounting/  # all accounting UI panels
  components/layout/    # Sidebar, AppBackdrop
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

The backend dir is bind-mounted (hot reload). The frontend container is a built image, so run `docker compose up --build -d frontend` before checking UI changes.

## First run

1. Set `BOOTSTRAP_ADMIN_EMAIL` and sign in with that Google account. It becomes the platform admin, but only while no admin exists.
2. Other people sign in once (they land on `/pending` as unverified). On **Platform admin**, click "Make firm" to turn someone into a firm owner.
3. The firm owner adds staff by email on **Team** and promotes managers there.
4. Billing is opt-in. With no page rate set, uploads are free and never blocked. Once a rate is set on Platform admin, each extracted page debits the firm's budget and uploads stop at ₱0.

## Env vars

Required in production: `GEMINI_API_KEY`, `JWT_SECRET` (≥32 chars), `GOOGLE_CLIENT_ID`; insecure defaults fail startup. Also: `DATABASE_URL`, `ENVIRONMENT`, `FRONTEND_URL` (comma-separated CORS origins), `ACCOUNTING_GEMINI_MODEL`, `ACCOUNTING_GEMINI_THINKING_LEVEL`, `ACCOUNTING_DIR`, `MAX_FILE_SIZE_MB`, `MAX_BATCH_SIZE`, `BOOTSTRAP_ADMIN_EMAIL`, `JWT_SECRET_PREVIOUS`, `DATABASE_SSL_MODE`, `DATABASE_SSL_ROOT_CERT`, `DATABASE_POOLER`, Gemini rate-limit knobs. Frontend: `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_GOOGLE_CLIENT_ID`.

## Gotchas

- **aa_* tables have FORCE RLS** keyed on `app.current_user_id` → the user's firm. Every DB session that touches them must `bind_session_user` (`get_current_user` does it; background jobs like `pipeline.run_extraction` do it themselves). The app's DB role must be **NOBYPASSRLS** or RLS silently does nothing.
- **Firm scope:** every accounting row carries `enterprise_id` = the firm owner's user id (`routers/accounting_scope.scope_for`). Always filter by it, even with RLS on.
- **Storage:** documents go to `ACCOUNTING_DIR` (falls back to `backend/uploads/` in dev, gitignored). Tax records must be kept ≥5 years, so prod needs a long-retention volume. In production the upload endpoint returns 503 until `ACCOUNTING_DIR` is set.
- **Schema changes:** add aa_* columns to the model *and* `services/accounting/schema.py` (for existing DBs). Destructive changes go in `alembic/` (empty so far; `start.sh` runs `alembic upgrade head`).
- **Transaction pooler (port 6543):** statement caches are off. No session state across transactions (`SET LOCAL`/`set_config(..., true)` only), no advisory locks, temp tables or LISTEN/NOTIFY.
- **CORS middleware must be added LAST** in `main.py` so it wraps everything and answers preflight.
- **Abuse middleware** blocks empty User-Agent always and bot UAs (`curl`, `python-requests`…) in prod; skips `/api/health` + `OPTIONS`.
- **In-memory rate limiters** are per instance; N instances ≈ N× the limit.
- **Spreadsheet output:** run every untrusted cell through `spreadsheet_safe.csv_safe` (formula injection).
- **PDF templates** are calibrated comb-cell layouts (`forms/overlay.py`); re-calibrate when BIR revises a form.
- **Tailwind `dark:`** follows the OS here; use the theme CSS vars instead.
- **Frontend token** lives in `sessionStorage` (`autoaccounting_token`). The axios interceptor attaches it, and on 401 it is cleared and AuthGate redirects.

## Open items carried over

Alphalist DAT export (BIR layout unverified), Gemini read of scanned payroll registers, 1604-E, 1702-RT balance sheet not yet defaulted from books, manual contribution remittances, WC010 vs WC011 manual, whether IEIRD landed cost feeds COGS (ask CPA). Deploy pipeline not set up yet (`Dockerfile.prod` files exist for both apps).

## Conventions

- Python: type hints, `Mapped[...]`, `X | None`; routers raise `HTTPException`, services raise `ValueError`.
- Logging: structured key=value; auth events → `auth.audit`, Gemini → `gemini`.
- Frontend: strict TS, `@/*` → `src/*`, page-scoped `useState`; accounting UI lives under `components/accounting`.
