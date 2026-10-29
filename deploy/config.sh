# Non-secret production settings, sourced by setup-gcp.sh and deploy.sh.
# Secrets live in Secret Manager (AA_* secrets, created by setup-gcp.sh).

PROJECT_ID="autoaccounting-ph"   # a new GCP project, kept apart from SnagStock's billing and IAM
REGION="asia-southeast1"           # Singapore: closest region to Manila; Supabase project should be ap-southeast-1
REPO="autoaccounting"              # Artifact Registry repository
BACKEND_SERVICE="aa-backend"
FRONTEND_SERVICE="aa-frontend"

UPLOADS_BUCKET="${PROJECT_ID}-uploads"        # client documents (ACCOUNTING_DIR), versioned
BACKUPS_BUCKET="${PROJECT_ID}-db-backups"     # nightly pg_dump (30 days) + monthly (6 years)
BUILD_BUCKET="${PROJECT_ID}-cloudbuild-asia"  # Cloud Build source staging in-region (no cross-region egress)

# Public URLs. Empty = the services' default run.app URLs (deploy.sh works them out).
# With a custom domain: API_URL="https://api.example.com", FRONTEND_URL="https://example.com,https://<run.app url>".
API_URL=""
FRONTEND_URL=""

# Google OAuth web client ID (public; same value as NEXT_PUBLIC_GOOGLE_CLIENT_ID).
GOOGLE_CLIENT_ID="415242727441-dtd3ipiukurk52rjg35v4rjfn5to668d.apps.googleusercontent.com"

# The Google account that becomes platform admin on first sign-in (only while no admin exists).
BOOTSTRAP_ADMIN_EMAIL="matthewfrasersim@gmail.com"

# Extraction model (same as local .env).
GEMINI_MODEL="gemini-3.8-flash"
GEMINI_THINKING_LEVEL="low"

# Assistant on hosted Qwen (DashScope key in AA_ASSISTANT_LLM_API_KEY). An empty base URL turns it off
# (503 "not configured"); the "assistant" switch on Platform admin hides it.
ASSISTANT_LLM_BASE_URL="https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
ASSISTANT_LLM_MODEL="qwen3.8-flash"
