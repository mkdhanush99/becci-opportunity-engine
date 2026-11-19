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
