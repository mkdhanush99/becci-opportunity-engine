# BECCI OPPORTUNITY ENGINE — PHASE 2
## FORMAL ACCEPTANCE REPORT

**Date:** November 19, 2026  
**Project:** BECCI Opportunity Intelligence Engine — Phase 2 (Tender Scout & Government Procurement Discovery)  
**Repository:** `/Users/dhanushmakam/.gemini/antigravity/scratch/becci-opportunity-engine`  
**Acceptance Verdict:** **APPROVED — ALL PHASE 2 ACCEPTANCE STANDARDS VERIFIED**  

---

## 1. Phase 2 Final Acceptance Standard Verification

| Acceptance Criterion | Status | Verifiable Evidence |
|---|---|---|
| **1. Genuine discovery from officially supported public procurement sources** | **PASS** | 25 genuine tenders discovered and persisted in `data/becci.db` across 3 officially permitted sources: **CPPP eProcure** (`cppp-eprocure`: 10 tenders), **GeM Public Bids** (`gem-public-bids`: 5 bids + official PDFs), and **SIDBI Institutional Tenders** (`sidbi-tenders`: 10 RFPs/empanelments; 7 SARFAESI auctions filtered). |
| **2. Traceable official source links** | **PASS** | Every discovered tender links directly to its official government portal or Bid Document PDF (`https://bidplus.gem.gov.in/showbidDocument/<id>`, `https://eprocure.gov.in/eprocure/app`, `https://www.sidbi.in/en/tenders`). |
| **3. Supporting evidence for important claims** | **PASS** | Every extracted claim (Title, Reference No, Issuing Authority, Deadline, Bid Opening Date, Estimated Value, EMD, Tender Fee, Turnover, Experience, MSME Preference) creates an `Evidence` row anchored to a verbatim source snippet. |
| **4. Deadline and cancellation handling** | **PASS** | `evaluate_tender_status()` and `handle_deduplication_and_changes()` track `upcoming`, `open`, `closing_soon`, `extended`, `cancelled`, `under_verification`, and `expired`. Cancellations transition records to `LifecycleStatus.WITHDRAWN` and `VerificationStatus.REMOVED`. |
| **5. Duplicate & corrigendum handling** | **PASS** | Re-running `cppp-eprocure` produced `items_seen: 10, items_new: 0, items_unchanged: 10`. Corrigendums match by `reference_number` or `tender_id`, extend deadlines, append to `corrigendum_history`, and save `OpportunityVersion` snapshots. |
| **6. Agent 07 Verification integration** | **PASS** | `verify_opportunity()` evaluates 4 tender-specific checks (`tender_reference_consistency`, `tender_deadline_evidence`, `tender_corrigendum_and_status`, `tender_eligibility_intelligence`) alongside the 5 core verification checks. All 25 live tenders passed with `official_confirmed`. |
| **7. API & Admin security controls** | **PASS** | Public `/api/v1/tenders` exposes only approved/published non-fixture tenders (3 published; 22 held in `needs_human_review`). Admin endpoints require HMAC-SHA256 bearer tokens and RBAC role checks. |
| **8. Phase 1 regression tests pass** | **PASS** | All 10 Phase 1 opportunities (5 Jobs + 5 Funding Schemes) remain intact in `data/becci.db`, and all 19 Phase 1 unit/integration tests + `test_phase1_agents_regression` pass with 0 regressions. |
| **9. New tests pass in isolated database** | **PASS** | **30 / 30 tests passed (100% pass rate, 74% statement coverage)** against isolated `data/test_becci.db` (`tests/conftest.py`). |
| **10. Source limitations documented honestly** | **PASS** | `mahatenders-nic` (`robots.txt: Disallow: /`) and `telangana-etender` (`login.html` CSRF handshake) were tested live, recorded as `ScanStatus.BLOCKED` / `support_status = "unsupported"`, and documented in `docs/TENDER_SOURCE_FEASIBILITY_REPORT.md`. |

---

## 2. Source Integration Inventory (`data/becci.db`)

| Source ID | Agent ID | Collection Method | Support Status | Active | Live Scan Outcome |
|---|---|---|---|---|---|
| `tgpsc-whats-new` | `job_scout` | `http_html` + PDF | `supported` | Yes | Phase 1 Verified (2 jobs, 35 process notices skipped) |
| `mpsc-advertisements` | `job_scout` | `browser` | `supported` | Yes | Phase 1 Verified (3 jobs, 7 corrigendums skipped) |
| `nbcfdc-schemes` | `funding_scout` | `http_html` | `supported` | Yes | Phase 1 Verified (3 loan schemes) |
| `sidbi-schemes` | `funding_scout` | `sitemap` | `supported` | Yes | Phase 1 Verified (2 MSME schemes) |
| `gem-public-bids` | `tender_scout` | `search_interface` + PDF | `supported` | Yes | **Phase 2 Verified** (5 bids + official GeM Bid PDFs) |
| `cppp-eprocure` | `tender_scout` | `http_html` | `supported` | Yes | **Phase 2 Verified** (10 active tenders + detail views) |
| `sidbi-tenders` | `tender_scout` | `browser` | `supported` | Yes | **Phase 2 Verified** (10 RFPs, 7 SARFAESI auctions skipped) |
| `upsc-recruitment` | `job_scout` | `http_html` | `unsupported` | No | Akamai WAF HTTP 403 |
| `msme-ministry` | `funding_scout` | `http_html` | `unsupported` | No | Akamai WAF HTTP 403 |
| `mahatenders-nic` | `tender_scout` | `http_html` | `unsupported` | No | **Blocked by `robots.txt` (`Disallow: /`)** |
| `telangana-etender` | `tender_scout` | `http_html` | `unsupported` | No | **Blocked by `login.html` CSRF session handshake** |

---

## 3. Known Limitations & Operational Notes

1. **State Portal Access Controls (`mahatenders.gov.in`, `tender.telangana.gov.in`):** Direct crawling of these two state NIC/eProcurement portals is restricted by `robots.txt` (`Disallow: /`) and a mandatory `login.html` form gate respectively. In compliance with BECCI security rules, neither restriction is bypassed. Central government, national highway, defence, atomic energy, and PSU tenders located in **Maharashtra** and **Telangana** are captured via `cppp-eprocure` and `gem-public-bids`.
2. **CPPP Session-Scoped Detail Links:** CPPP `DirectLink` URLs on `eprocure.gov.in/eprocure/app` are bound to the active Tapestry `JSESSIONID` cookie created during the home page request. `TenderScout` fetches detail pages within the same `HttpFetcher` session during the scan and sets `original_url` to the canonical portal URL (`https://eprocure.gov.in/eprocure/app`) while recording the `Tender ID` and `Tender Reference Number` for permanent lookup.
3. **Human Review Gate:** Newly discovered tenders default to `lifecycle_status = "needs_human_review"` and are never auto-published without administrator approval.

---

## 4. Deployment & Verification Commands

```bash
cd /Users/dhanushmakam/.gemini/antigravity/scratch/becci-opportunity-engine
source .venv/bin/activate
export PYTHONPATH=.

# 1. Run database migrations & seed sources
python cli.py init-db

# 2. Execute live Tender Scout scans
python cli.py scan --source cppp-eprocure
python cli.py scan --source gem-public-bids
python cli.py scan --source sidbi-tenders

# 3. Run full isolated test suite (30 tests: Phase 1 + Phase 2)
PYTHONPATH=. pytest -v --cov=app --cov-report=term-missing
```
