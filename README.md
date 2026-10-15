# AutoAccounting

AI back office for accounting firms: drop client receipts and invoices, and AutoAccounting extracts, sorts and files them by company, year and quarter.

## Run it locally

You need [Docker Desktop](https://www.docker.com/products/docker-desktop/) running.

1. **Create your settings file** (first time only):

   ```bash
   cp .env.example .env
   ```

   Then open `.env` and set:

   - `GEMINI_API_KEY`: needed to read documents.
   - `ENABLE_DEV_LOGIN=true`: lets you sign in without setting up Google (see below).

2. **Start everything:**

   ```bash
   docker compose up --build -d
   ```

   The first start takes a few minutes while it installs dependencies. After that it's quick.

3. **Open the app:** http://localhost:3001

   - `/` is the landing page.
   - **Log in**, then **Sign in with Google**, puts you straight into the app as the platform admin.

| What | Where |
|---|---|
| App + landing page | http://localhost:3001 |
| Backend API | http://localhost:8001 (health check: `/api/health`) |
| Database (Postgres) | `localhost:5433` |

### Editing: no restarts needed

Both the frontend and backend watch your files. Save a change and it shows up on its own: refresh the browser for the landing page, and the app pages update automatically. You do **not** need to rerun Docker.

You only need to rebuild when you:

- **add or update a package** (`package.json` or `backend/pyproject.toml`) → `docker compose up --build -d --renew-anon-volumes`
- **change `.env`** → `docker compose up -d --force-recreate`

### Signing in

Google sign-in isn't set up yet. While `.env` has `ENVIRONMENT=development` and `ENABLE_DEV_LOGIN=true`, the login page shows a stand-in **Sign in with Google** button that signs you straight in as the platform admin. It doesn't contact Google, and there's no password, so keep it to your own machine. The backend refuses to start with `ENABLE_DEV_LOGIN` on outside development.

To switch to real Google sign-in, set `NEXT_PUBLIC_GOOGLE_CLIENT_ID` (and `BOOTSTRAP_ADMIN_EMAIL` to claim the admin account on a fresh database), then run `docker compose up --build -d`. The real Google button replaces the stand-in automatically.

### Everyday commands

```bash
docker compose ps                  # what's running
docker compose logs -f backend     # watch backend logs (or: frontend)
docker compose stop                # stop everything (data is kept)
docker compose up -d               # start again
docker compose down -v             # stop AND wipe the database (careful)
```

### Checks

```bash
docker compose exec backend python -m pytest -q          # backend tests
docker compose exec backend ruff check app --select F,E9 # backend lint
cd frontend && npm install && npm run lint && npx tsc --noEmit
```

## Project layout

- `frontend/`: Next.js app. The marketing landing page is plain HTML in `frontend/public/` (`index.html`, `styles.css`, `app.js`).
- `backend/`: FastAPI + Postgres.
- `CLAUDE.md`: deeper architecture notes and gotchas.
