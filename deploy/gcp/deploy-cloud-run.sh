#!/usr/bin/env bash
# Deploy BECCI Opportunity Intelligence Engine to Google Cloud Run (asia-south1 Mumbai)
set -euo pipefail

PROJECT_ID="${1:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${2:-asia-south1}"
SERVICE_NAME="${3:-becci-opportunity-engine}"

if [ -z "$PROJECT_ID" ]; then
  echo "Usage: $0 <GCP_PROJECT_ID> [REGION=asia-south1] [SERVICE_NAME=becci-opportunity-engine]"
  exit 1
fi

SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')

echo "==> Enabling Cloud Run, Cloud Build, and Artifact Registry APIs on project ${PROJECT_ID}"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com --project="$PROJECT_ID"

echo "==> Deploying ${SERVICE_NAME} to Cloud Run (${REGION})"
gcloud run deploy "$SERVICE_NAME" \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --source=. \
  --allow-unauthenticated \
  --memory=2Gi \
  --cpu=2 \
  --min-instances=1 \
  --max-instances=1 \
  --timeout=300 \
  --set-env-vars="BECCI_ENV=production,BECCI_DATABASE_URL=sqlite:///./data/becci.db,BECCI_SECRET_KEY=${SECRET_KEY},BECCI_ADMIN_TOKEN_TTL_MINUTES=480,BECCI_ENFORCE_DOMAIN_ALLOWLIST=true,BECCI_AUTO_APPROVE_OFFICIAL_CONFIRMED=false"

SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" --project="$PROJECT_ID" --region="$REGION" --format="value(status.url)")
echo ""
echo "==> LIVE CLOUD RUN URL: ${SERVICE_URL}"
curl -fsS "${SERVICE_URL}/api/v1/health" && echo ""
