#!/usr/bin/env bash
# Deploy BECCI Opportunity Intelligence Engine to Azure Container Apps (centralindia)
set -euo pipefail

RESOURCE_GROUP="${1:-rg-becci}"
LOCATION="${2:-centralindia}"
APP_NAME="${3:-becci-opportunity-engine}"
ENV_NAME="${4:-env-becci}"

echo "==> Deploying to Azure Container Apps"
echo "    Resource Group: $RESOURCE_GROUP"
echo "    Location:       $LOCATION"
echo "    App Name:       $APP_NAME"

# 1. Create Resource Group if not exists
az group create --name "$RESOURCE_GROUP" --location "$LOCATION" --output table

# 2. Register required resource providers
az provider register --namespace Microsoft.App --wait
az provider register --namespace Microsoft.OperationalInsights --wait

# 3. Generate Secret Key
SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')

# 4. Deploy Container App using source code / Dockerfile
az containerapp up \
  --name "$APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --location "$LOCATION" \
  --environment "$ENV_NAME" \
  --source . \
  --ingress external \
  --target-port 8000 \
  --env-vars \
    BECCI_ENV=production \
    BECCI_DATABASE_URL=sqlite:///./data/becci.db \
    BECCI_SECRET_KEY="$SECRET_KEY" \
    BECCI_ADMIN_TOKEN_TTL_MINUTES=480 \
    BECCI_ENFORCE_DOMAIN_ALLOWLIST=true \
    BECCI_AUTO_APPROVE_OFFICIAL_CONFIRMED=false

# 5. Retrieve FQDN
FQDN=$(az containerapp show --name "$APP_NAME" --resource-group "$RESOURCE_GROUP" --query "properties.configuration.ingress.fqdn" -o tsv)
SERVICE_URL="https://${FQDN}"

echo ""
echo "=========================================================="
echo "==> LIVE AZURE CONTAINER APP URL: ${SERVICE_URL}"
echo "=========================================================="
curl -fsS "${SERVICE_URL}/api/v1/health" && echo ""
