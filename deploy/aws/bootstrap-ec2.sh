#!/usr/bin/env bash
# Bootstrap & deploy BECCI Opportunity Intelligence Engine on Ubuntu 24.04 EC2
set -euo pipefail

APP_DIR="/opt/becci-opportunity-engine"
API_DOMAIN="${1:-api.becci.in}"

echo "==> Installing system dependencies (Python 3.12, Caddy, Playwright Chromium deps)"
sudo apt-get update -y
sudo apt-get install -y python3.12 python3.12-venv python3-pip git curl caddy

sudo mkdir -p "$APP_DIR"
sudo chown -R ubuntu:ubuntu "$APP_DIR"
cd "$APP_DIR"

if [ ! -d ".venv" ]; then
  python3.12 -m venv .venv
fi

.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium
sudo .venv/bin/playwright install-deps chromium

if [ ! -f ".env" ]; then
  SECRET=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
  cat > .env <<EOF
BECCI_ENV=production
BECCI_DATABASE_URL=sqlite:///./data/becci.db
BECCI_SECRET_KEY=${SECRET}
BECCI_ADMIN_TOKEN_TTL_MINUTES=480
BECCI_CORS_ORIGINS=["https://becci.in","https://www.becci.in","https://preview.becci.in"]
BECCI_ENFORCE_DOMAIN_ALLOWLIST=true
BECCI_AUTO_APPROVE_OFFICIAL_CONFIRMED=false
EOF
  chmod 600 .env
fi

sudo cp deploy/aws/becci-engine.service /etc/systemd/system/becci-engine.service
sudo systemctl daemon-reload
sudo systemctl enable --now becci-engine

sudo sed "s/api.becci.in/${API_DOMAIN}/g" deploy/aws/Caddyfile | sudo tee /etc/caddy/Caddyfile > /dev/null
sudo systemctl reload caddy

echo "==> Verifying local FastAPI health"
sleep 3
curl -fsS http://127.0.0.1:8000/api/v1/health && echo ""
echo "==> BECCI Opportunity Engine deployed. Point DNS A record for ${API_DOMAIN} to this EC2 public IP for automatic HTTPS."
