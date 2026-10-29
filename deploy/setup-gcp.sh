#!/usr/bin/env bash
# One-time Google Cloud setup for AutoAccounting production. Safe to re-run: existing resources are kept.
#
#   bash deploy/setup-gcp.sh
#
# Needs: gcloud signed in as a project owner, a billing account, and the Supabase connection strings
# (deploy/README.md step 2). Prompts for secrets it hasn't stored yet; nothing secret is written to disk.
set -euo pipefail
cd "$(dirname "$0")"
source ./config.sh

say() { printf '\n== %s\n' "$*"; }
g() { gcloud --project "$PROJECT_ID" "$@"; }

# ── Project + APIs ───────────────────────────────────────────────────────────
say "Project $PROJECT_ID"
if ! gcloud projects describe "$PROJECT_ID" >/dev/null 2>&1; then
  gcloud projects create "$PROJECT_ID" --name "AutoAccounting"
  echo "Link a billing account, then re-run:"
  echo "  gcloud billing accounts list"
  echo "  gcloud billing projects link $PROJECT_ID --billing-account <ACCOUNT_ID>"
  exit 1
fi
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')

say "APIs"
g services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  secretmanager.googleapis.com cloudscheduler.googleapis.com iam.googleapis.com storage.googleapis.com

# ── Artifact Registry ────────────────────────────────────────────────────────
say "Artifact Registry $REPO"
g artifacts repositories describe "$REPO" --location "$REGION" >/dev/null 2>&1 ||
  g artifacts repositories create "$REPO" --repository-format docker --location "$REGION"
# Keep the 10 newest images of each service; older ones are only rollback targets.
cat > /tmp/aa-ar-cleanup.json <<'JSON'
[{"name":"keep-recent","action":{"type":"Keep"},"mostRecentVersions":{"keepCount":10}},
 {"name":"delete-old","action":{"type":"Delete"},"condition":{"olderThan":"30d"}}]
JSON
g artifacts repositories set-cleanup-policies "$REPO" --location "$REGION" --policy /tmp/aa-ar-cleanup.json --no-dry-run >/dev/null

# ── Buckets ──────────────────────────────────────────────────────────────────
bucket() {  # name
  g storage buckets describe "gs://$1" >/dev/null 2>&1 ||
    g storage buckets create "gs://$1" --location "$REGION" --uniform-bucket-level-access --public-access-prevention
}

say "Uploads bucket gs://$UPLOADS_BUCKET (client documents)"
bucket "$UPLOADS_BUCKET"
# Versioned: an overwritten or deleted document stays recoverable for 30 days. No retention lock: the app
# deletes duplicates and renames compressed copies, which a locked bucket would refuse.
g storage buckets update "gs://$UPLOADS_BUCKET" --versioning --soft-delete-duration=30d >/dev/null
cat > /tmp/aa-uploads-lifecycle.json <<'JSON'
{"rule":[{"action":{"type":"Delete"},"condition":{"isLive":false,"daysSinceNoncurrentTime":30}}]}
JSON
g storage buckets update "gs://$UPLOADS_BUCKET" --lifecycle-file /tmp/aa-uploads-lifecycle.json >/dev/null

say "Backups bucket gs://$BACKUPS_BUCKET"
bucket "$BACKUPS_BUCKET"
cat > /tmp/aa-backups-lifecycle.json <<'JSON'
{"rule":[
  {"action":{"type":"Delete"},"condition":{"age":30,"matchesPrefix":["nightly/"]}},
  {"action":{"type":"SetStorageClass","storageClass":"COLDLINE"},"condition":{"age":30,"matchesPrefix":["monthly/"]}},
  {"action":{"type":"Delete"},"condition":{"age":2190,"matchesPrefix":["monthly/"]}}
]}
JSON
g storage buckets update "gs://$BACKUPS_BUCKET" --lifecycle-file /tmp/aa-backups-lifecycle.json >/dev/null

say "Cloud Build staging bucket gs://$BUILD_BUCKET"
bucket "$BUILD_BUCKET"
cat > /tmp/aa-build-lifecycle.json <<'JSON'
{"rule":[{"action":{"type":"Delete"},"condition":{"age":7}}]}
JSON
g storage buckets update "gs://$BUILD_BUCKET" --lifecycle-file /tmp/aa-build-lifecycle.json >/dev/null

# ── Service accounts ─────────────────────────────────────────────────────────
sa() {  # id, display name
  g iam service-accounts describe "$1@$PROJECT_ID.iam.gserviceaccount.com" >/dev/null 2>&1 ||
    g iam service-accounts create "$1" --display-name "$2"
}
say "Service accounts"
sa aa-backend "AutoAccounting backend (Cloud Run)"
sa aa-frontend "AutoAccounting frontend (Cloud Run)"
sa aa-db-backup "AutoAccounting nightly Supabase pg_dump"
sa aa-build "AutoAccounting Cloud Build deploys"
BACKEND_SA="aa-backend@$PROJECT_ID.iam.gserviceaccount.com"
FRONTEND_SA="aa-frontend@$PROJECT_ID.iam.gserviceaccount.com"
BACKUP_SA="aa-db-backup@$PROJECT_ID.iam.gserviceaccount.com"
BUILD_SA="aa-build@$PROJECT_ID.iam.gserviceaccount.com"   # deploy.sh runs builds as this account

# ── Secrets ──────────────────────────────────────────────────────────────────
secret() {  # name, prompt, [generated value]
  if g secrets describe "$1" >/dev/null 2>&1; then
    echo "$1: exists (add a version with: gcloud secrets versions add $1 --data-file=-)"
    return
  fi
  local value="${3:-}"
  if [ -z "$value" ]; then
    read -r -s -p "$2: " value; echo
  fi
  printf '%s' "$value" | g secrets create "$1" --data-file=- --replication-policy automatic >/dev/null
  echo "$1: created"
}
say "Secrets"
echo "Supabase URLs: see deploy/README.md step 2 (app = transaction pooler 6543 as aa_app, backup = session pooler 5432 as postgres)."
secret AA_DATABASE_URL "AA_DATABASE_URL (postgresql+asyncpg://aa_app.<ref>:<pw>@<pooler-host>:6543/postgres)"
secret AA_DB_BACKUP_URL "AA_DB_BACKUP_URL (postgresql://postgres.<ref>:<pw>@<pooler-host>:5432/postgres?sslmode=require)"
secret AA_GEMINI_API_KEY "AA_GEMINI_API_KEY"
secret AA_JWT_SECRET "" "$(openssl rand -hex 32)"
secret AA_ASSISTANT_LLM_API_KEY "AA_ASSISTANT_LLM_API_KEY (DashScope key)"

# ── IAM ──────────────────────────────────────────────────────────────────────
say "IAM"
for s in AA_DATABASE_URL AA_GEMINI_API_KEY AA_JWT_SECRET AA_ASSISTANT_LLM_API_KEY; do
  g secrets add-iam-policy-binding "$s" --member "serviceAccount:$BACKEND_SA" \
    --role roles/secretmanager.secretAccessor >/dev/null
done
g secrets add-iam-policy-binding AA_DB_BACKUP_URL --member "serviceAccount:$BACKUP_SA" \
  --role roles/secretmanager.secretAccessor >/dev/null
gcloud storage buckets add-iam-policy-binding "gs://$UPLOADS_BUCKET" --member "serviceAccount:$BACKEND_SA" \
  --role roles/storage.objectAdmin >/dev/null
gcloud storage buckets add-iam-policy-binding "gs://$BACKUPS_BUCKET" --member "serviceAccount:$BACKUP_SA" \
  --role roles/storage.objectAdmin >/dev/null

# Cloud Build reads its staged source, pushes images, deploys both services and acts as their service accounts.
for role in roles/run.admin roles/artifactregistry.writer roles/logging.logWriter; do
  g projects add-iam-policy-binding "$PROJECT_ID" --member "serviceAccount:$BUILD_SA" --role "$role" \
    --condition None >/dev/null
done
gcloud storage buckets add-iam-policy-binding "gs://$BUILD_BUCKET" --member "serviceAccount:$BUILD_SA" \
  --role roles/storage.objectAdmin >/dev/null
for target in "$BACKEND_SA" "$FRONTEND_SA"; do
  g iam service-accounts add-iam-policy-binding "$target" --member "serviceAccount:$BUILD_SA" \
    --role roles/iam.serviceAccountUser >/dev/null
done

# ── Nightly database backup (Cloud Run Job + Cloud Scheduler) ────────────────
# Stock postgres image, no custom build ("^~~^" makes ~~ gcloud's list separator, so the script can hold commas
# and pipes). Runs as Supabase's postgres role (BYPASSRLS), so FORCE RLS tables dump whole. Written to /tmp first so a half-written dump never lands in the bucket; the 1st of each month is also
# kept under monthly/ for 6 years. The nightly connection also keeps a free-tier Supabase project from pausing.
say "Backup job"
BACKUP_SCRIPT='set -euo pipefail
stamp=$(date -u +%Y%m%dT%H%MZ)
pg_dump "$DUMP_URL" -Fc --no-owner --no-acl --schema=public -f /tmp/db.dump
mkdir -p /backups/nightly /backups/monthly
cp /tmp/db.dump "/backups/nightly/autoaccounting-$stamp.dump"
if [ "$(TZ=Asia/Manila date +%d)" = "01" ]; then cp /tmp/db.dump "/backups/monthly/autoaccounting-$stamp.dump"; fi
ls -l /backups/nightly | tail -3'
job_flags=(
  --region "$REGION" --image docker.io/library/postgres:17 --service-account "$BACKUP_SA"
  --set-secrets DUMP_URL=AA_DB_BACKUP_URL:latest
  --add-volume "name=backups,type=cloud-storage,bucket=$BACKUPS_BUCKET"
  --add-volume-mount volume=backups,mount-path=/backups
  --memory 1Gi --cpu 1 --task-timeout 1800 --max-retries 1
  --command bash --args="^~~^-c~~$BACKUP_SCRIPT"
)
if g run jobs describe aa-db-backup --region "$REGION" >/dev/null 2>&1; then
  g run jobs update aa-db-backup "${job_flags[@]}" >/dev/null
else
  g run jobs create aa-db-backup "${job_flags[@]}" >/dev/null
fi
g run jobs add-iam-policy-binding aa-db-backup --region "$REGION" --member "serviceAccount:$BACKUP_SA" \
  --role roles/run.invoker >/dev/null

say "Backup schedule (03:00 Manila)"
g scheduler jobs describe aa-db-backup-nightly --location "$REGION" >/dev/null 2>&1 ||
  g scheduler jobs create http aa-db-backup-nightly --location "$REGION" \
    --schedule "0 3 * * *" --time-zone "Asia/Manila" --http-method POST \
    --uri "https://run.googleapis.com/v2/projects/$PROJECT_ID/locations/$REGION/jobs/aa-db-backup:run" \
    --oauth-service-account-email "$BACKUP_SA" >/dev/null

say "Done. Next: bash deploy/deploy.sh"
