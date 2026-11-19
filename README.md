# BECCI Opportunity Intelligence Engine

Autonomous Browser-Based Research Agents | Real-World Opportunity Discovery | Verification | Backend Platform

Organisation: **Bahujan Entrepreneurs Chamber for Commerce & Industry (BECCI)**

---

## 1. Quick Start ("TRY NOW")

The project is completely self-contained in Python 3.12+ with FastAPI, SQLAlchemy, Playwright, and Pydantic.

### Activate Virtual Environment
```bash
cd /Users/dhanushmakam/.gemini/antigravity/scratch/becci-opportunity-engine
source .venv/bin/activate
export PYTHONPATH=.
```

### Initialise Database & Seed Sources
```bash
python cli.py init-db
python cli.py list-sources
```

### Run Autonomous Research Scans
```bash
# 1. Job Scout: Telangana Public Service Commission
python cli.py scan --source tgpsc-whats-new

# 2. Job Scout: Maharashtra Public Service Commission (Headless Chromium)
python cli.py scan --source mpsc-advertisements

# 3. Funding Scout: National Backward Classes Finance & Development Corp
python cli.py scan --source nbcfdc-schemes

# 4. Funding Scout: SIDBI MSME Loan Products
python cli.py scan --source sidbi-schemes
```

### List Discovered Opportunities
```bash
python cli.py list-opportunities
```

### Human Review & Publication
```bash
# Transition an opportunity from review to published
python cli.py review --opp <OPPORTUNITY_ID_OR_PREFIX> --action publish --reason "Verified official notification"
```

### Run the FastAPI Server
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
- Interactive API Docs (Swagger): `http://localhost:8000/docs`
- Health Check: `http://localhost:8000/api/v1/health`
- Public Opportunities: `http://localhost:8000/api/v1/opportunities`
- Admin Review Queue: `http://localhost:8000/api/admin/queue` (Bearer token authenticated)
- System Metrics: `http://localhost:8000/api/admin/metrics`

Default Administrator Credentials:
- **Username**: `admin`
- **Password**: `BecciAdmin2026!`

### Run Automated Tests
```bash
PYTHONPATH=. pytest -v
```

---

## 2. System Architecture

```
[Registered Sources] 
         │
         ▼
[Research Orchestrator] ─── Concurrency Semaphores & Domain Whitelists
         │
         ├──► AGENT 01: Job Scout (TGPSC, MPSC)
         └──► AGENT 02: Funding Scout (NBCFDC, SIDBI)
                     │
                     ▼
             [Content Extraction] ──► Immutable Raw Captures & Snippet Evidence
                     │
                     ▼
             [Normalisation] ──► Slugs, Fingerprints & Geographic Classifications
                     │
                     ▼
             [Deduplication] ──► Fuzzy Title Match & Version Snapshots
                     │
                     ▼
             [Verification Agent] ──► 7-Point Integrity Check (Domain, Dates, Evidence)
                     │
                     ▼
             [Human Review Queue] ──► Admin Approval / Presentation Editing
                     │
                     ▼
             [Public API v1] ──► Verified Opportunities + BECCI Disclaimers
```

---

## 3. Supported vs Unsupported Sources (Integrity Policy)

| Source ID | Organisation | Method | Status | Notes |
|---|---|---|---|---|
| `tgpsc-whats-new` | Telangana PSC | HTTP + PDF | Supported | Discovers gazetted recruitment notifications & PDFs |
| `mpsc-advertisements` | Maharashtra PSC | Browser (Playwright) | Supported | Renders JS table of advertisements & corrigendums |
| `nbcfdc-schemes` | NBCFDC (Ministry of Social Justice) | HTTP | Supported | Discovers backward-class business loan schemes |
| `sidbi-schemes` | SIDBI | Sitemap + HTTP | Supported | Discovers direct MSME credit & green finance |
| `upsc-recruitment` | Union Public Service Commission | HTTP | Unsupported | Akamai WAF returns HTTP 403 to automated crawlers; never bypassed |
| `msme-ministry` | Ministry of MSME | HTTP | Unsupported | Akamai WAF returns HTTP 403 on robots.txt; never bypassed |
