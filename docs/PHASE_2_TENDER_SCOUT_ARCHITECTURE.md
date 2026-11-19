# BECCI OPPORTUNITY ENGINE — PHASE 2
## TENDER SCOUT ARCHITECTURE & DATA FLOW SPECIFICATION

**Component:** Agent 03 — Tender Scout (`tender_scout`)  
**Version:** 2.0.0  
**Status:** Production Architecture Specification  

---

## 1. Architectural Principles

1. **Zero Disruption to Phase 1:** `JobScout`, `FundingScout`, `VerificationRecord`, `Evidence`, `OpportunityVersion`, and existing `/api/v1/opportunities` endpoints remain backward-compatible.
2. **Unified Opportunity Spine with Structured Tender Extension:** Every tender is stored as a first-class `Opportunity` (`category = "tender"`) in the primary SQLite/PostgreSQL database, joined 1-to-1 with a dedicated `tender_details` table (`TenderDetail` ORM model) via an explicit, reversible migration (`app/migrations.py`).
3. **No Fabricated Defaults:** When a procurement source does not publish an estimated value, EMD, tender fee, or MSME exemption, the engine explicitly records `"Not published"` or `"Not stated"` rather than inventing numbers.
4. **Traceable Evidence for Every Claim:** Every extracted procurement attribute (reference number, deadline, bid opening date, estimated value, EMD, turnover requirement, MSME preference) creates a corresponding `Evidence` row containing the verbatim source snippet and URL.
5. **Corrigendum & Cancellation Lifecycle:** Corrigendum notices and deadline extensions match existing tenders by `reference_number` or `tender_id`, transition `tender_status` to `extended` (or `cancelled` upon cancellation notice), update the deadline, append to `corrigendum_history`, and create an immutable `OpportunityVersion` snapshot.

---

## 2. System Data Flow

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                         SOURCE REGISTRY (TENDER SOURCES)                     │
│  • gem-public-bids (Supported: GeM JSON Search + Bid Document PDF)           │
│  • cppp-eprocure   (Supported: CPPP eProcure Active Tenders + Corrigendums)  │
│  • sidbi-tenders   (Supported: SIDBI Institutional RFPs via Playwright)      │
│  • mahatenders-nic (Unsupported: Disallowed by robots.txt)                   │
│  • telangana-etender (Unsupported: Gated by login.html CSRF gate)            │
└──────────────────────────────────────┬───────────────────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                SCHEDULER & RESEARCH ORCHESTRATOR (app/orchestrator/)         │
│  • JobLock concurrency control (prevents overlapping scans)                  │
│  • Exponential backoff retry on transient network/5xx errors                 │
│  • Immediate halt (ScanStatus.BLOCKED) on robots.txt / 403 / CAPTCHA / login │
│  • Per-source failure isolation (one failed source never blocks others)      │
└──────────────────────────────────────┬───────────────────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                     AGENT 03 — TENDER SCOUT (app/agents/tender_scout.py)     │
│  1. Discovery & Extraction (GeM / CPPP / SIDBI parsers)                      │
│  2. BECCI 11-Sector Classification (Manufacturing, IT, Construction, etc.)   │
│  3. Geographic Classification (National, State, District, Local)             │
│  4. Eligibility Intelligence Extraction (MSME, Udyam, GST, PAN, Turnover, JV)│
│  5. Deadline State Machine (upcoming, open, closing_soon, extended, expired) │
└──────────────────────────────────────┬───────────────────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│           NORMALISATION, DEDUPLICATION & CORRIGENDUM MERGE ENGINE            │
│  • Normalises Opportunity + TenderDetail 1-to-1 record                       │
│  • Matches duplicates by Tender ID, Reference No, URL, or Title (RapidFuzz)  │
│  • Applies corrigendum deadline extensions & cancellation updates            │
│  • Preserves prior state in OpportunityVersion audit history                 │
└──────────────────────────────────────┬───────────────────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                   AGENT 07 — VERIFICATION AGENT INTEGRATION                  │
│  • Domain authenticity check against Source.official_domains                 │
│  • Tender reference & publication evidence grounding check                   │
│  • Deadline & bid opening date coherence check                               │
│  • Eligibility & corrigendum consistency check                               │
│  • Routes ambiguous or active records to NEEDS_HUMAN_REVIEW                  │
└──────────────────────────────────────┬───────────────────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                 HUMAN REVIEW & VERSIONED API (/api/v1 & /api/admin)          │
│  • GET  /api/v1/tenders (Public approved/published tenders + filters)        │
│  • GET  /api/v1/tenders/{id_or_slug} (Full tender details + disclaimer)      │
│  • GET  /api/admin/tenders (Admin view with evidence & verification checks)  │
│  • POST /api/admin/scheduler/run-due (Controlled scheduled execution)        │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Database Schema & Migration Design (`tender_details`)

The `tender_details` table extends `opportunities` via a 1-to-1 foreign key (`opportunity_id -> opportunities.id ON DELETE CASCADE`):

| Column | Type | Description |
|---|---|---|
| `opportunity_id` | `VARCHAR(32) PK, FK` | Links 1-to-1 with `opportunities.id` |
| `tender_id` | `VARCHAR(128) INDEX` | Portal-specific unique ID (e.g., `2026_MoRTH_934941_1`, `GEM/2026/B/8055173`) |
| `reference_number` | `VARCHAR(128) INDEX` | Official NIT / RFP reference number |
| `issuing_authority` | `VARCHAR(255)` | Ministry or primary statutory authority |
| `department` | `VARCHAR(255)` | Specific department, division, or office chain |
| `tender_category` | `VARCHAR(64)` | `Works`, `Goods`, `Services`, `Consultancy`, `Empanelment` |
| `product_category` | `VARCHAR(255)` | Detailed product/service description from notice |
| `sector` | `VARCHAR(64) INDEX` | One of the 11 BECCI sector classifications |
| `estimated_value` | `VARCHAR(128)` | Published tender value in INR, or `"Not published"` |
| `emd_amount` | `VARCHAR(128)` | Earnest Money Deposit in INR, or `"Not published"` |
| `tender_fee` | `VARCHAR(128)` | Tender document fee in INR, or `"Not published"` |
| `document_download_date` | `DATE NULL` | Document download end date, if published |
| `pre_bid_date` | `DATE NULL` | Pre-bid meeting date, if scheduled |
| `pre_bid_details` | `TEXT` | Pre-bid venue/address or `"Not published"` |
| `bid_opening_date` | `DATE NULL` | Technical/bid opening date |
| `turnover_requirement` | `VARCHAR(255)` | Minimum annual turnover wording or `"Not stated"` |
| `experience_requirement` | `TEXT` | Past experience requirement wording or `"Not stated"` |
| `required_registrations` | `JSON` | List of detected registration/licence requirements (GST, PAN, Udyam, OEM, etc.) |
| `msme_preference` | `TEXT` | Explicit MSE/Startup relaxation or purchase preference wording, or `"Not stated"` |
| `eligibility_intelligence` | `JSON` | Structured breakdown (`msme_eligible`, `udyam_required`, `gst_required`, `pan_required`, `jv_allowed`, `ambiguous`) |
| `tender_status` | `VARCHAR(32) INDEX` | `upcoming`, `open`, `closing_soon`, `closed`, `cancelled`, `extended`, `under_verification`, `expired` |
| `corrigendum_history` | `JSON` | List of applied corrigendums / extensions (`[{title, date, old_deadline, new_deadline, url}]`) |
| `cancellation_reason` | `TEXT NULL` | Recorded if a tender is cancelled or withdrawn |

---

## 4. BECCI 11-Sector Classification Mapping

Every tender is deterministically classified into one of the 11 required BECCI sectors using keyword and product-category rules:
1. `Manufacturing` (machinery, equipment, fabrication, chemicals, textiles, luminaires, electrical goods, cables, bollard, valves, spares)
2. `Trading and distribution` (supply of stationery, office supplies, consumables, containers, furniture, general goods)
3. `Services` (security agency, housekeeping, manpower, maintenance, AMC, repair, hiring of vehicles, inspection, due diligence)
4. `Healthcare` (medical, hospital, surgical, laparoscopic, cholangioscopy, ultrasound, pharmaceutical, laboratory, diagnostic)
5. `Education and training` (school, university, classroom, training, skill development, simulator, library, educational)
6. `Agriculture and allied activities` (agriculture, irrigation, dairy, fisheries, fertilizer, seeds, horticulture, veterinary, forestry)
7. `IT and technology` (software, hardware, server, network, data aggregator, CCTV, ANPR camera, NVR, telecom, cloud, GIS, display screen)
8. `Construction and infrastructure` (civil works, road, highway, slope protection, building, bridge, godown, boundary wall, renovation, water supply, metro)
9. `Finance and professional services` (consultancy, audit, legal, financial, insurance, valuation, implementing agency, project management)
10. `Hospitality and tourism` (catering, canteen, hotel, event management, travel, tourism, guest house)
11. `Other industries` (fallback when notice does not match a specialized sector)
