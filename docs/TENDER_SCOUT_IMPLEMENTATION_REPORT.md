# BECCI OPPORTUNITY ENGINE — PHASE 2
## TENDER SCOUT IMPLEMENTATION REPORT

**Date:** November 19, 2026  
**Component:** Agent 03 — Tender Scout (`app/agents/tender_scout.py`)  
**Engine Version:** 2.0.0  

---

## 1. Executive Summary of Implementation

Phase 2 extends the accepted Phase 1 BECCI Opportunity Intelligence Engine with **Agent 03 — Tender Scout**, a government and public-sector procurement discovery, classification, and verification capability. All accepted Phase 1 modules (`JobScout`, `FundingScout`, `VerificationRecord`, `Evidence`, `OpportunityVersion`, and existing Phase 1 database records) remain intact.

### Summary of Live Discovery Results (`data/becci.db`):
- **Phase 1 Records Preserved:** 10 genuine opportunities (5 Jobs + 5 Funding Schemes) untouched.
- **Phase 2 Genuine Tenders Discovered:** **25 real procurement tenders** across 3 officially permitted public sources:
  - **Central Public Procurement Portal (`cppp-eprocure`):** 10 active tenders + 9 corrigendums evaluated, enriched with session-scoped `DirectLink` detail pages.
  - **Government e-Marketplace (`gem-public-bids`):** 5 active public bids discovered via the official GeM search interface (`all-bids-data`) and enriched with unencrypted official GeM Bid Document PDFs (`/showbidDocument/<id>`).
  - **SIDBI Institutional Tenders (`sidbi-tenders`):** 17 notices scanned via headless Chromium (Playwright); **10 genuine procurement RFPs/Empanelments extracted** and **7 SARFAESI distressed-asset property auctions excluded**.
- **Unsupported State Portals Transparently Recorded:**
  - `mahatenders-nic` (`mahatenders.gov.in`): Blocked by `robots.txt` (`Disallow: /`) -> `ScanStatus.BLOCKED` / `unsupported`.
  - `telangana-etender` (`tender.telangana.gov.in`): Blocked by mandatory JS login form CSRF handshake -> `ScanStatus.BLOCKED` / `unsupported`.

---

## 2. Database Migration Details (`app/migrations.py`)

Database evolution is managed by `app/migrations.py`, which maintains a `schema_migrations` tracking table and executes explicit, reversible SQL migrations while preserving SQLite WAL compatibility:

1. **`001_phase1_baseline`:** Baseline Phase 1 tables (`sources`, `opportunities`, `evidence`, `verification_records`, `opportunity_versions`, `opportunity_sources`, `scan_runs`, `raw_captures`, `job_locks`, `admin_users`, `audit_log`).
2. **`002_phase2_tender_details`:** Creates the `tender_details` 1-to-1 extension table (`FOREIGN KEY(opportunity_id) REFERENCES opportunities(id) ON DELETE CASCADE`) and indexes on `tender_id`, `reference_number`, `sector`, and `tender_status`.
3. **Reversibility:** `rollback_migration("002_phase2_tender_details")` drops the indexes and `tender_details` table cleanly without affecting `opportunities`.

---

## 3. Capabilities Implemented in Agent 03 (`app/agents/tender_scout.py`)

### 3.1 Multi-Source Discovery & Extraction
- **`gem_public_bids`:** Fetches CSRF session token from `https://bidplus.gem.gov.in/all-bids`, queries `POST https://bidplus.gem.gov.in/all-bids-data`, and downloads official GeM Bid Document PDFs (`/showbidDocument/<id>`) to extract Bid No, Ministry, Department, Organisation, Item Category, Quantity, Start/End Dates, Bid Opening Date, Estimated Value, EMD, Turnover requirement, Past Experience requirement, and MSE/Startup relaxations. Includes an HTML `.card` parser fallback.
- **`cppp_eprocure`:** Parses both the **Latest Tenders** and **Latest Corrigendums** tables on `https://eprocure.gov.in/eprocure/app` and follows session-scoped `DirectLink` URLs to extract `Organisation Chain`, `Tender ID`, `Tender Reference Number`, `Tender Category`, `Product Category`, `Tender Value in ₹`, `EMD Amount in ₹`, `Tender Fee in ₹`, `Pre Bid Meeting Date/Address`, `Location`, `Document Download End Date`, `Bid Submission Start/End Date`, `Bid Opening Date`, and `NDA/Pre Qualification`.
- **`sidbi_tenders`:** Uses headless Chromium (`BrowserEngine`) to render `https://www.sidbi.in/en/tenders`, extracts RFPs and empanelment notices, and filters out SARFAESI property recovery auctions.

### 3.2 Missing Field Policy
Never fabricates missing data. Unstated financial attributes (`estimated_value`, `emd_amount`, `tender_fee`, `pre_bid_details`) default explicitly to `"Not published"`, and unstated eligibility attributes (`turnover_requirement`, `experience_requirement`, `msme_preference`) default to `"Not stated"`.

### 3.3 BECCI 11-Sector & Geographic Classification
- `classify_sector()` maps every tender to one of the 11 BECCI sectors (`Manufacturing`, `Trading and distribution`, `Services`, `Healthcare`, `Education and training`, `Agriculture and allied activities`, `IT and technology`, `Construction and infrastructure`, `Finance and professional services`, `Hospitality and tourism`, `Other industries`).
- `classify_geography()` determines `state`, `city`, and `location_type` (`national`, `state`, `district`, `local`) from explicit location fields, titles, and organisation chains.

### 3.4 Eligibility Intelligence & Deadline Monitoring
- `extract_eligibility_intelligence()` extracts structured indicators for MSME eligibility, Udyam certificate requirement, GST, PAN, Manufacturer/OEM status, licences/ATC certificates, past experience, annual turnover, consortium/JV clauses, and sets `ambiguous_flag = True` when criteria defer to external documents.
- `evaluate_tender_status()` computes status across `upcoming`, `open`, `closing_soon`, `closed`, `cancelled`, `extended`, `under_verification`, and `expired`.

### 3.5 Corrigendum, Cancellation, Deduplication & Agent 07 Verification
- Matching corrigendums by `reference_number` or `tender_id` update the deadline, set `tender_status = "extended"`, append to `corrigendum_history`, and create an `OpportunityVersion` snapshot.
- Cancellation notices transition `tender_status` to `"cancelled"`, `lifecycle_status` to `WITHDRAWN`, and `VerificationStatus.REMOVED`.
- Agent 07 (`app/pipeline/verification.py`) executes 4 dedicated procurement checks (`tender_reference_consistency`, `tender_deadline_evidence`, `tender_corrigendum_and_status`, `tender_eligibility_intelligence`) in addition to the 5 baseline security/evidence gates.

---

## 4. API & Admin Console Updates

### Public API (`/api/v1`)
- `GET /api/v1/tenders` — Lists approved and published tenders with filters for `state`, `sector`, `tender_status`, `deadline_before`, `deadline_after`, and `q` (department, ministry, title, or tender reference number).
- `GET /api/v1/tenders/{id_or_slug}` — Returns a single verified public tender including its `tender_detail` object and mandatory BECCI disclaimer.
- `GET /api/v1/opportunities` — Enhanced with `sector`, `tender_status`, `deadline_before`, and `deadline_after` filters.

### Admin API (`/api/admin`)
- `GET /api/admin/tenders` — Lists all discovered tenders across all lifecycle statuses with full procurement filtering.
- `GET /api/admin/tenders/{opp_id}` — Returns full tender details, `tender_detail`, verbatim `evidence` snippets, and `verification_records`.
- `GET /api/admin/sources/health` — Returns all registered sources and active failure/block alerts.
- `POST /api/admin/scheduler/run-due` — Triggers scheduled discovery across due active sources with `JobLock` concurrency control, exponential backoff retry, and per-source failure isolation.
- **Admin Web Console (`app/static/index.html`):** Added one-click scan triggers for `GeM Public Bids`, `CPPP eProcure`, and `SIDBI RFPs & Tenders`.

---

## 5. Real-Source Evidence Samples from `data/becci.db`

### Sample 1: CPPP Central Highway Infrastructure Tender (Maharashtra)
- **External Key:** `cppp:2026_MoRTH_934941_1`
- **Tender ID / Reference:** `2026_MoRTH_934941_1` / `NIT No.24/EENHD/PEN/3277/2026-27`
- **Title:** *Special Repairs of Slope Protection Work along Varandh Ghat from Km 91.000 to 94.000 of NH-965 DD in the State of Maharashtra during FY 2026-27*
- **Issuing Authority:** Ministry of Road Transport and Highways (`P6 Delhi - MoRTH | RO Mumbai - MoRTH | NH Maharashtra PWD-Pen - MoRTH`)
- **State / City / Level:** `Maharashtra` / `Mumbai` (`district`)
- **Sector:** `Construction and infrastructure`
- **Estimated Value:** `INR 8,02,01,914`
- **EMD Amount:** `INR 16,04,000`
- **Tender Fee:** `INR 10,000`
- **Pre-Bid Meeting:** `2026-12-11` (`Superintending Engineer, National Highway Circle, (P.W.), 6th floor C.B.D. Belapur Konkan Bhavan, Navi Mumbai -400614`)
- **Published / Deadline / Opening:** `2026-11-19` / `2026-12-18` / `2026-12-21`
- **Required Registrations:** `["GST Registration", "BharatKosh Fee Receipt", "Power of Attorney / Bid Security"]`
- **Verification Status:** `official_confirmed` (8 evidence snippets anchored)

### Sample 2: CPPP Department of Atomic Energy Tender (Mumbai, Maharashtra)
- **External Key:** `cppp:2026_DAE_934937_1`
- **Tender ID / Reference:** `2026_DAE_934937_1` / `TIFR/PD/SQ26-45/261757`
- **Title:** *87-217 G Plan Apo 50X Objective Mitutoyo Microscope Objective -Model Number 378-848-3*
- **Issuing Authority:** Department of Atomic Energy (`Tata Institute of Fundamental Research-Colaba-Mumbai-Purchase Department`)
- **Estimated Value / EMD / Fee:** `INR 5,86,989` / `INR 11,740` / `INR 0.00`
- **Published / Deadline / Opening:** `2026-11-19` / `2026-11-30` / `2026-12-01`
- **Verification Status:** `official_confirmed`

### Sample 3: GeM Public Bid with Official PDF Extraction
- **External Key:** `gem:GEM/2026/B/8055173`
- **Tender ID / Reference:** `GEM/2026/B/8055173`
- **Title:** *GeM Bid GEM/2026/B/8055173: LED Luminaire For Road And Street Lights Conforming To IS 10322 (Part 5/Section 3) (V3) (Under BIS Scheme - II)*
- **Issuing Authority:** `Panchayats and Rural Housing Department Gujarat`
- **Official Bid PDF URL:** `https://bidplus.gem.gov.in/showbidDocument/9914154`
- **Experience Requirement:** `3 Year (s)`
- **MSME Preference:** `MSE Relaxation (Experience & Turnover): Yes | Complete; MSE Purchase Preference (L-1 + 15%) applicable with valid Udyam Certificate`
- **Published / Deadline:** `2026-09-18` / `2027-05-31` (`tender_status = extended`)
- **Verification Status:** `official_confirmed`

### Sample 4: SIDBI Institutional RFP
- **External Key:** `sidbi-tender:empanelment-of-implementing-agencies-ias-for-promoting-financing-and-adoption-of`
- **Title:** *Empanelment of Implementing Agencies (IAs) for Promoting Financing and Adoption of Energy-Efficient and Renewable Energy Technologies among Rural and Semi-Urban Enterprises under the MoRE Program*
- **Issuing Authority:** `Small Industries Development Bank of India (SIDBI)`
- **Published / Deadline:** `2026-11-16` / `2026-12-15` (`tender_status = open`)
- **Verification Status:** `official_confirmed`
