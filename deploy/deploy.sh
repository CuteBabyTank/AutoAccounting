#!/usr/bin/env bash
# Build both images in Cloud Build and deploy them to Cloud Run (cloudbuild.yaml).
#
#   bash deploy/deploy.sh
#
# Deploys the working tree as it is (uncommitted changes included); commit first so a deploy maps to a commit.
set -euo pipefail
cd "$(dirname "$0")/.."
source deploy/config.sh

if [ -z "$GOOGLE_CLIENT_ID" ] || [ -z "$BOOTSTRAP_ADMIN_EMAIL" ]; then
  echo "Set GOOGLE_CLIENT_ID and BOOTSTRAP_ADMIN_EMAIL in deploy/config.sh first." >&2
  exit 1
fi
if [ -n "$(git status --porcelain)" ]; then
  echo "Warning: uncommitted changes are included in this deploy." >&2
fi

# Cloud Run's deterministic URLs: https://<service>-<project number>.<region>.run.app
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
API_URL="${API_URL:-https://$BACKEND_SERVICE-$PROJECT_NUMBER.$REGION.run.app}"
FRONTEND_URL="${FRONTEND_URL:-https://$FRONTEND_SERVICE-$PROJECT_NUMBER.$REGION.run.app}"

echo "API:      $API_URL"
echo "Frontend: $FRONTEND_URL"

gcloud builds submit --project "$PROJECT_ID" --config cloudbuild.yaml \
  --service-account "projects/$PROJECT_ID/serviceAccounts/aa-build@$PROJECT_ID.iam.gserviceaccount.com" \
  --gcs-source-staging-dir "gs://$BUILD_BUCKET/source" \
  --substitutions "^##^_REGION=$REGION##_REPO=$REPO##_BACKEND_SERVICE=$BACKEND_SERVICE##_FRONTEND_SERVICE=$FRONTEND_SERVICE##_UPLOADS_BUCKET=$UPLOADS_BUCKET##_API_URL=$API_URL##_FRONTEND_URL=$FRONTEND_URL##_GOOGLE_CLIENT_ID=$GOOGLE_CLIENT_ID##_BOOTSTRAP_ADMIN_EMAIL=$BOOTSTRAP_ADMIN_EMAIL##_GEMINI_MODEL=$GEMINI_MODEL##_GEMINI_THINKING_LEVEL=$GEMINI_THINKING_LEVEL##_ASSISTANT_LLM_BASE_URL=$ASSISTANT_LLM_BASE_URL##_ASSISTANT_LLM_MODEL=$ASSISTANT_LLM_MODEL"

echo
echo "Deployed. Open $(echo "$FRONTEND_URL" | cut -d, -f1)"
