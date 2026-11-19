# BECCI Opportunity Engine — Phase 4 Production Readiness Assessment

**Date:** 2026-11-19  
**Current Mode:** Live Staging Preview on Hostinger (`https://preview.becci.in`) backed by Virtual HTTPS Tunnel (`https://leaving-honors-friendly-generating.trycloudflare.com`)

---

## 1. Ready Now (Verified Live)
- Public opportunity discovery, filtering, and detail pages hosted on Hostinger (`preview.becci.in`).
- Member registration, login, protected routes, 3-step business profile onboarding, personalised matching dashboard, saved/viewed tracking.
- Strict separation between public, member, and admin endpoints; main production site `becci.in` preserved untouched.

## 2. Known Limitations (Virtual Staging Mode)
1. **Temporary Virtual Backend Tunnel:** The FastAPI backend is currently running locally (`127.0.0.1:8000`) and exposed via a Cloudflare quick tunnel (`trycloudflare.com`). If this local machine sleeps or the tunnel restarts, the staging API URL will stop responding until a permanent VPS/cloud backend is deployed.
2. **Password Recovery:** Self-service email password reset is not yet implemented in the backend (requires SMTP/email provider configuration); documented honestly rather than simulated.
3. **Published Record Count:** Currently 3 verified tenders are published (`lifecycle_status = 'published'`); 32 additional `official_confirmed` opportunities await human review/publication in the Admin Review Console (`${API_BASE_URL}/admin`).

## 3. Production Deployment Requirements (Next Step When Ready)
1. Deploy `becci-opportunity-engine` (FastAPI + SQLite/PostgreSQL + Playwright) on a persistent Linux VPS (e.g., Hostinger KVM VPS) behind HTTPS at `https://api.becci.in`.
2. Set `BECCI_SECRET_KEY` (strong random 32+ byte secret) and `BECCI_ENV=production` in server environment variables.
3. Rebuild `becci-opportunity-portal` with `VITE_BECCI_API_BASE_URL=https://api.becci.in` and redeploy to `preview.becci.in` or link from `becci.in`.

## Live Cloud Production Deployment Sign-Off (2026-11-19)

### 1. Live Deployment Topology
- **Backend API Host:** Azure App Service (Linux `PYTHON|3.12`, SKU: `B1`, Region: `Central India` / Pune)
  - **Live URL:** `https://becci-api.azurewebsites.net`
  - **Health Check:** `https://becci-api.azurewebsites.net/api/v1/health`
  - **Metadata Endpoint:** `https://becci-api.azurewebsites.net/api/v1/metadata`
  - **Opportunities Endpoint:** `https://becci-api.azurewebsites.net/api/v1/opportunities`
  - **CORS Allowed Origins:** `https://preview.becci.in`, `https://becci.in`, `https://www.becci.in`, `http://localhost:5173`
- **Frontend Portal Host:** Hostinger Web Hosting (Static SPA + `.htaccess` routing)
  - **Live Portal URL:** `https://preview.becci.in`
  - **Main Production Site Untouched:** `https://becci.in`

### 2. Verification Results
- `GET https://becci-api.azurewebsites.net/api/v1/health` -> HTTP 200 `{"status": "healthy", "service": "BECCI Opportunity Intelligence Engine", "version": "3.0.0"}`
- `GET https://becci-api.azurewebsites.net/api/v1/opportunities?limit=5` -> HTTP 200 with genuine opportunities loaded from `data/becci.db`.
- `OPTIONS https://becci-api.azurewebsites.net/api/v1/opportunities` with `Origin: https://preview.becci.in` -> HTTP 200 `Access-Control-Allow-Origin: https://preview.becci.in`.
- `GET https://preview.becci.in` -> HTTP 200, serving React 18 SPA pointing directly to Azure backend.
