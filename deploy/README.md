# Deploying AutoAccounting

Production runs the same way as SnagStock: both apps on **Cloud Run** in `asia-southeast1` (Singapore), the database
on **Supabase** (plain hosted Postgres behind its transaction pooler), client documents in a **Cloud Storage bucket**
mounted into the backend, and our own nightly `pg_dump` to Cloud Storage.

```
browser ──> aa-frontend (Cloud Run, Next.js)        scale to zero, ≤ 3 instances
   └──────> aa-backend  (Cloud Run, FastAPI)        scale to zero, 1 instance max
              ├─ /data  = gs://<project>-uploads    ACCOUNTING_DIR, versioned
              ├─ Supabase pooler :6543 as aa_app    NOBYPASSRLS, so FORCE RLS really filters
              ├─ Gemini API                         extraction
              └─ DashScope (hosted Qwen)            assistant, once a key is set
aa-db-backup (Cloud Run Job, 03:00 Manila) ── pg_dump as postgres ──> gs://<project>-db-backups
```

| File | What it does |
|---|---|
| `deploy/config.sh` | Project, region, names, public URLs, OAuth client ID (nothing secret) |
| `deploy/supabase-setup.sql` | Creates the `aa_app` role, pg_trgm, and locks out the Data API roles |
| `deploy/setup-gcp.sh` | One-time GCP setup: APIs, registry, buckets, service accounts, secrets, IAM, backup job + schedule |
| `deploy/deploy.sh` | Builds and deploys both services through `cloudbuild.yaml` |

Rough monthly cost at low traffic: Cloud Run ≈ $0–5, buckets + backups ≈ $1, Cloud Build within the free
120 min/day, Supabase free (or Pro $25), plus Gemini usage.

## 1. Google Cloud project

1. Edit `deploy/config.sh`: `PROJECT_ID` (globally unique), `GOOGLE_CLIENT_ID`, `BOOTSTRAP_ADMIN_EMAIL`.
2. `gcloud auth login`, then create the project and link billing (setup-gcp.sh stops and prints the commands if the
   project has no billing yet).

## 2. Supabase

1. New project, region **Southeast Asia (Singapore) `ap-southeast-1`**. Save the database (postgres) password.
2. **Integrations → Data API: turn it off** (no exposed schemas, "automatically expose new tables" off). We don't
   use Supabase Auth, Storage, Realtime or REST; it is plain Postgres here.
3. SQL editor: paste `deploy/supabase-setup.sql`, replace `CHANGE_ME` with `openssl rand -hex 24`, run it.
   Check `postgres` shows `rolbypassrls = true` and `aa_app` shows `false`.
4. **Connect → Connection pooler**: note the pooler host (`aws-0-ap-southeast-1.pooler.supabase.com` or similar) and
   the project ref. The two connection strings setup-gcp.sh asks for:

   ```
   AA_DATABASE_URL   postgresql+asyncpg://aa_app.<ref>:<aa_app password>@<pooler host>:6543/postgres
   AA_DB_BACKUP_URL  postgresql://postgres.<ref>:<postgres password>@<pooler host>:5432/postgres?sslmode=require
   ```

   The app URL must say `postgresql+asyncpg://` and carry no `?sslmode=` (asyncpg rejects it); SSL is forced by
   `start.sh` and verified with `backend/certs/supabase-prod-ca-2021.crt`. Port 6543 switches the app into
   transaction-pooler mode by itself (`database.py`).

Free tier: 500 MB database, no backups of its own (ours run nightly), pauses after 7 days without activity (the
nightly backup connects every night). Move to Pro before the firm's data outgrows it.

## 3. Google Cloud resources

```bash
bash deploy/setup-gcp.sh
```

It prompts for the two Supabase URLs, the Gemini key and the DashScope key (secrets it already has are
skipped), and generates `AA_JWT_SECRET`. Re-running it is safe.

## 4. Deploy

```bash
bash deploy/deploy.sh
```

The first deploy takes ~10 minutes. On boot the backend creates the `aa_*` tables, columns and RLS policies
(`startup_migrations`), then `alembic upgrade head`.

Then in the **Google Cloud console → APIs & Services → Credentials → the OAuth web client**, add the frontend URL
(printed by deploy.sh, `https://aa-frontend-<number>.asia-southeast1.run.app`) to *Authorized JavaScript origins*.
Sign in with `BOOTSTRAP_ADMIN_EMAIL`; that account becomes the platform admin.

## 5. Check it

```bash
source deploy/config.sh
gcloud run services logs read aa-backend --project $PROJECT_ID --region $REGION --limit 50
#   look for: db_config pooler=transaction ssl=require verify=True
gcloud run jobs execute aa-db-backup --project $PROJECT_ID --region $REGION --wait
gcloud storage ls -l gs://$BACKUPS_BUCKET/nightly/
```

Then upload a receipt and confirm it is extracted and filed.

**Restore test** (a backup you've never restored doesn't count):

```bash
LATEST=$(gcloud storage ls gs://$BACKUPS_BUCKET/nightly/ | sort | tail -1)
gcloud storage cp "$LATEST" /tmp/aa.dump
docker run -d --name aa-restore -e POSTGRES_PASSWORD=x postgres:17 && sleep 5
docker cp /tmp/aa.dump aa-restore:/tmp/aa.dump
docker exec aa-restore psql -U postgres -c "CREATE ROLE aa_app"
docker exec aa-restore pg_restore -U postgres -d postgres --no-owner /tmp/aa.dump
docker exec aa-restore psql -U postgres -c "select count(*) from aa_documents"
docker rm -f aa-restore
```

## Custom domain (later)

```bash
gcloud beta run domain-mappings create --service aa-frontend --domain app.example.com --region asia-southeast1
gcloud beta run domain-mappings create --service aa-backend  --domain api.example.com --region asia-southeast1
```

Add the DNS records it prints, then set in `deploy/config.sh`
`API_URL="https://api.example.com"` and `FRONTEND_URL="https://app.example.com,https://aa-frontend-<number>.asia-southeast1.run.app"`,
add the new origin to the OAuth client, and redeploy (the API URL is baked into the frontend build).

## Assistant (hosted Qwen)

On DashScope (`ASSISTANT_LLM_BASE_URL` / `ASSISTANT_LLM_MODEL` in `deploy/config.sh`, key in
`AA_ASSISTANT_LLM_API_KEY`). Rotate the key with
`printf '%s' '<key>' | gcloud secrets versions add AA_ASSISTANT_LLM_API_KEY --project $PROJECT_ID --data-file=-`
and redeploy. An empty base URL turns it off ("not configured"); the `assistant` switch on Platform admin hides it.

## Operating notes

- **Background jobs.** Extraction runs as an in-process task after the upload request returns, so the backend
  keeps its CPU between requests (`--no-cpu-throttling`, instance-based billing while an instance is up; it still
  scales to zero). With request-based CPU the job only advanced during the 2 s polls and a one-page receipt took
  minutes. A job killed by scale-in or a deploy is resumed on the next read of that upload
  (`jobs.stale_action`: no progress for 30 min → resume; older than 24 h → failed, re-drop). On shutdown the
  backend dates its unfinished uploads back so they resume at once (`pipeline.release_running`).
- **Upload compression.** Up to 3 PDFs compress at once (`compress.PDF_WORKERS`, 768 MB cap each), which is
  why the backend has 4 GiB. Lower the workers before lowering `--memory`.
- **One backend instance.** Rate limiters and per-firm job slots are in memory. Raising `--max-instances` multiplies
  them; move them to Postgres/Redis first.
- **Uploads bucket.** Versioned with 30-day noncurrent retention + 30-day soft delete. No retention lock: the app
  deletes duplicates and renames compressed copies, which a locked bucket refuses. Tax records stay because the app
  keeps them, not because the bucket forces it.
- **Backups.** `nightly/` kept 30 days; the 1st of each month also goes to `monthly/` (Coldline after 30 days,
  kept 6 years).
- **Taking the API offline:** `gcloud run services update aa-backend --ingress internal` (`--ingress all` to reopen).
- **Rollback:** `gcloud run services update-traffic aa-backend --to-revisions <REVISION>=100` (same for aa-frontend).
- **Auto-deploy on push:** a push to the `prod` branch runs the Cloud Build trigger `aa-prod-deploy` (global,
  GitHub app, branch `^prod$`, config `cloudbuild.yaml`, service account `aa-build`). It builds from the commit, not
  the working tree. Its substitutions are copies of `deploy/config.sh`; when that file changes, update the trigger
  (`gcloud builds triggers describe aa-prod-deploy` / `update github`). `deploy/deploy.sh` still works for one-off
  deploys of the local tree.
