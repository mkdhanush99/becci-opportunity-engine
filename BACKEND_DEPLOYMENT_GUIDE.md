# BECCI Opportunity Engine — Backend Deployment Guide

## 1. Hosting Architecture on Azure
- **Resource Group:** `rg-becci`
- **Region:** Central India (`centralindia`)
- **App Service Plan:** `plan-becci` (SKU `B1`, Linux Python 3.12, Basic tier)
- **App Service WebApp:** `becci-api`
- **Public Domain:** `https://becci-api.azurewebsites.net`
- **Always-On:** `true` (keeps background workers & schedulers running 24/7)

## 2. Persistent Storage Architecture
Azure Linux App Service uses a persistent SMB storage mount backed by `/home`.
- Database file path: `/home/data/becci.db`
- Preserved across container restarts, zip deployments, and scaling.
- Configured via environment variable: `BECCI_DATABASE_URL=sqlite:////home/data/becci.db`

## 3. Configuration & Secrets Management
Stored securely in Azure App Service Application Settings (never committed to Git):
```bash
az webapp config appsettings set -g rg-becci -n becci-api --settings \
  BECCI_ENV="production" \
  BECCI_DATABASE_URL="sqlite:////home/data/becci.db" \
  BECCI_AUTO_SCHEDULER_ENABLED="true" \
  BECCI_CRON_SECRET="<your-becci-cron-secret>" \
  APIFY_API_TOKEN="<your-apify-api-token>" \
  DEEPSEEK_API_KEY="<your-deepseek-api-key>" \
  DEEPSEEK_DEFAULT_MODEL="deepseek-flash" \
  DEEPSEEK_ADVANCED_MODEL="deepseek-v4-pro"
```

## 4. Deployment Procedure
To deploy updates:
```bash
# 1. Package code
zip -r /tmp/becci-api-deploy.zip app data/becci.db main.py startup.sh requirements.txt -x "**/__pycache__/*" "**/.pytest_cache/*"

# 2. Deploy to Azure
az webapp deploy --resource-group rg-becci --name becci-api --src-path /tmp/becci-api-deploy.zip --type zip
```

## 5. Logs & Monitoring
```bash
# Stream live logs
az webapp log tail --resource-group rg-becci --name becci-api
```
