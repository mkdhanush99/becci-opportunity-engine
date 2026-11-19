# BECCI OPPORTUNITY ENGINE — PHASE 2
## TENDER SOURCE FEASIBILITY REPORT

**Date of Assessment:** November 19, 2026  
**Prepared By:** Principal AI Systems Architect & Government Procurement Data Specialist  
**Target Agent:** Agent 03 — Tender Scout  

---

## 1. Assessment Methodology & Compliance Standards

Every candidate procurement source was evaluated live from the development environment against seven strict criteria:
1. **Official Domain & Authority:** Ownership by a central ministry, statutory body, state government, or PSU.
2. **`robots.txt` Policy:** Evaluated for `User-agent: *` and `BECCI-OpportunityBot`. Any `Disallow: /` rule immediately disqualifies automated collection.
3. **Public Access Without Authentication:** Verified whether tender listings and detail pages can be read without vendor login credentials or digital signature certificates (DSC).
4. **Anti-Bot / CAPTCHA Presence:** Checked whether listing or detail endpoints require solving a CAPTCHA or proof-of-work challenge.
5. **Preferred Discovery Mechanism:** Prioritised structured JSON search interfaces and official downloadable PDFs over raw DOM scraping where available.
6. **Field Richness:** Assessed availability of tender reference numbers, issuing department, estimated value, EMD, tender fee, submission deadlines, bid opening dates, and MSME/Udyam eligibility rules.
7. **Geographic & Sector Coverage:** Relevance to BECCI entrepreneurs across National, Telangana, Maharashtra, and pan-India MSME sectors.

---

## 2. Feasibility Matrix Across Priority Tiers

| Priority Tier | Source ID | Official Source Name | Official Domain | Public Access | `robots.txt` Status | Auth / CAPTCHA on Public List | Supported Discovery Method | Extraction Feasibility | Integration Status |
|---|---|---|---|---|---|---|---|---|---|
| **Priority 1 (GeM)** | `gem-public-bids` | Government e-Marketplace (GeM) Public Bids | `bidplus.gem.gov.in` | HTTP 200 (Public) | **Permitted** (`HTTP 200`; `/all-bids` & `/showbidDocument/` allowed; only `/resources/` & `/bg_emd/` disallowed) | None on `/all-bids`, `/all-bids-data`, or `/showbidDocument/<id>` PDF | Public Search Interface (`POST /all-bids-data` JSON) + Official Bid Document PDF (`/showbidDocument/<id>`) + Browser Fallback | **High** (Bid No, Ministry, Dept, Category, Quantity, Start/End Dates, Estimated Value, EMD, Turnover, Experience, MSE/Startup Exemption) | **SUPPORTED (Integrated)** |
| **Priority 2 (CPPP)** | `cppp-eprocure` | Central Public Procurement Portal (eProcurement System Govt of India) | `eprocure.gov.in` | HTTP 200 (Public) | **Permitted** (`HTTP 404` on `/robots.txt` — no crawler restrictions published) | None on `/eprocure/app` Active Tenders, Corrigendums, or DirectLink Tender Detail views | HTTP HTML Table Extraction + Session-preserved DirectLink Detail Page Extraction | **High** (Tender ID, Reference No, Organisation Chain, Category, Tender Value, EMD, Tender Fee, Pre-Bid Date, Opening Date, Closing Date, Location, Corrigendums) | **SUPPORTED (Integrated)** |
| **Priority 3 (State — Maharashtra)** | `mahatenders-nic` | Maharashtra eTender Portal (MahaTenders) | `mahatenders.gov.in` | HTTP 200 | **Disallowed** (`HTTP 200`; `User-agent: *` -> `Disallow: /`) | N/A — Blocked by `robots.txt` policy | None (Automated crawling prohibited by site policy) | **Blocked by Policy** (Note: Central & NH/PWD tenders in Maharashtra are captured via CPPP `eprocure.gov.in` and GeM) | **UNSUPPORTED (Policy Disallow)** |
| **Priority 3 (State — Telangana)** | `telangana-etender` | Telangana State eProcurement Portal | `tender.telangana.gov.in` | HTTP 200 (Redirects to `login.html` POST with CSRF handshake) | `HTTP 404` | Requires interactive session/login handshake (`document.loginForm.submit()`) & search CAPTCHA | None (Gated by login/session gate) | **Blocked by Access Gate** (Note: Central PSU/Institutional tenders in Telangana such as Hyderabad/Nagarjuna Sagar are captured via CPPP and GeM) | **UNSUPPORTED (Auth Gate)** |
| **Priority 4 (PSU / Institutional)** | `sidbi-tenders` | Small Industries Development Bank of India — Institutional Tenders & RFPs | `www.sidbi.in` | HTTP 200 (Public) | **Permitted** (`HTTP 200`; `User-agent: *` -> `Allow: /`, `Disallow: /head/`) | None | Headless Browser (Playwright) Table Extraction on `/en/tenders` & `/en/tenders/tenderarchived` | **High** (RFPs, Empanelment Notices, Vendor Due Diligence Tenders, Publication Date, Submission Deadline; filters out SARFAESI property auctions) | **SUPPORTED (Integrated)** |

---

## 3. Detailed Source Verification Findings

### 3.1 Priority 1: Government e-Marketplace (`bidplus.gem.gov.in`)
- **Official URL:** `https://bidplus.gem.gov.in/all-bids`
- **`robots.txt` Verification (`https://bidplus.gem.gov.in/robots.txt`):**
  ```text
  User-agent: *
  Disallow: /resources/
  Disallow: /bg_emd/epbgservice/CallBG_Performance_Status
  Disallow: /bg_emd/epbgservice/PBGIntimation
  Disallow: /bg_emd/epbgservice/AddSellerIssuinginfo
  ```
  Public bid discovery on `/all-bids`, `/all-bids-data`, and `/showbidDocument/<id>` is permitted.
- **Technical Discovery Mechanism:**
  1. Initial `GET https://bidplus.gem.gov.in/all-bids` establishes a public guest session cookie and provides the page token `csrf_bd_gem_nk`.
  2. `POST https://bidplus.gem.gov.in/all-bids-data` with filter `{"bidStatusType": "ongoing_bids", "byType": "all", "sort": "Bid-End-Date-Latest"}` returns structured JSON records containing `b_id`, `b_bid_number`, `bd_category_name`, `b_total_quantity`, `ba_official_details_minName`, `ba_official_details_deptName`, `final_start_date_sort`, and `final_end_date_sort`.
  3. For each discovered bid (`b_bid_type == 1`), `GET https://bidplus.gem.gov.in/showbidDocument/<b_id>` returns an unencrypted official bilingual GeM Bid Document PDF containing explicit fields for:
     - **Ministry / Department / Organisation Name**
     - **Estimated Bid Value in INR**
     - **EMD Amount & Advisory Bank**
     - **Minimum Average Annual Turnover (Lakhs)**
     - **Years of Past Experience Required**
     - **MSE Relaxation for Experience & Turnover (`Yes | Complete` / `No`)**
     - **Startup Relaxation for Experience & Turnover**
     - **MSE Purchase Preference (`L-1 + 15%` with valid Udyam Registration)**
     - **Required Documents from Seller**
- **Last Successful Live Verification:** `2026-11-19T12:46:18+05:30` (44,660 active bids available; PDF extraction verified on `GEM/2026/B/8193555` and active 2027 bids).

### 3.2 Priority 2: Central Public Procurement Portal (`eprocure.gov.in`)
- **Official URL:** `https://eprocure.gov.in/eprocure/app`
- **`robots.txt` Verification (`https://eprocure.gov.in/robots.txt`):** Returns `HTTP 404` (no crawler exclusions published).
- **Technical Discovery Mechanism:**
  1. `GET https://eprocure.gov.in/eprocure/app` returns two public tables without CAPTCHA:
     - **Latest Tenders** (Title, Reference No, Closing Date, Bid Opening Date, and session-scoped `DirectLink` URL).
     - **Latest Corrigendums** (Corrigendum Title/Type, Reference No, Revised Closing Date, Revised Opening Date, and `DirectLink` URL).
  2. Following each `DirectLink` within the same HTTP client session retrieves the full **Tender Details** view containing:
     - `Organisation Chain` (e.g., `Ministry of Road Transport and Highways||...||NH Maharashtra PWD-Pen`)
     - `Tender Reference Number` & `Tender ID` (e.g., `2026_MoRTH_934941_1`)
     - `Tender Category` (`Works`, `Goods`, `Services`) & `Product Category`
     - `Tender Fee in ₹` & `Tender Fee Exemption Allowed`
     - `EMD Amount in ₹` & `EMD Exemption Allowed`
     - `Tender Value in ₹`
     - `Pre Bid Meeting Date`, `Place`, and `Address`
     - `Location` & `Pincode`
     - `Critical Dates` (`Published Date`, `Document Download Start/End Date`, `Bid Submission Start/End Date`, `Bid Opening Date`)
     - `NDA / Pre Qualification` and `Independent External Monitor / Remarks` (e.g., GST reverse charge requirements)
- **Last Successful Live Verification:** `2026-11-19T12:42:22+05:30` (10 active tenders + 10 active corrigendums extracted; full detail page verified on `2026_MoRTH_934941_1`).

### 3.3 Priority 3: State Procurement Portals (`mahatenders.gov.in`, `tender.telangana.gov.in`)
- **Maharashtra (`https://mahatenders.gov.in/nicgep/app`):**
  - `https://mahatenders.gov.in/robots.txt` explicitly contains `User-agent: *` / `Disallow: /`.
  - Our `RobotsCache` enforces this rule and raises `BlockedError("disallowed by robots.txt")`. Registered in the Source Registry with `support_status = "unsupported"` and `active = False`.
- **Telangana (`https://tender.telangana.gov.in/`):**
  - Root page executes a mandatory JavaScript POST to `login.html` with a session CSRF gate. Registered in the Source Registry with `support_status = "unsupported"` and `active = False`.
- **Mitigation for State Coverage:** Both CPPP (`eprocure.gov.in`) and GeM (`bidplus.gem.gov.in`) publish central government, national highway, defence, railway, and PSU tenders located in **Telangana** (e.g., Nagarjuna Sagar / Hyderabad) and **Maharashtra** (e.g., Raigad / Pen / Mumbai / Kamptee / Nagpur). Our geographic classifier extracts the state and location directly from the CPPP detail page (`Location`, `Organisation Chain`, `Title`) and GeM department/item descriptions.

### 3.4 Priority 4: Public Sector & Institutional Procurement (`www.sidbi.in/en/tenders`)
- **Official URL:** `https://www.sidbi.in/en/tenders`
- **`robots.txt` Verification (`https://www.sidbi.in/robots.txt`):** Explicitly permits all crawlers (`Allow: /`, `Disallow: /head/`).
- **Technical Discovery Mechanism:**
  - Rendered via Playwright (`BrowserEngine`), the `/en/tenders` and `/en/tenders/tenderarchived` tables list institutional procurement notices with `S. No.`, `Title`, `Tender Date`, `Last Date Of Submission`, and `Remark`.
  - **Filtering Rule:** Distinguishes genuine procurement RFPs/Empanelments (e.g., *Empanelment of Implementing Agencies for Energy-Efficient Technologies*, *RFP for Subscription of Data Aggregator Services Provider*, *Engagement of Vendor for Machinery Supplier Due Diligence*, *Hiring of Security Agency*) from SARFAESI Act distressed-asset auction notices (`E-Auction Sale Notice... under SARFAESI Act, 2002`), skipping SARFAESI auctions with an explicit `skip_reason`.
- **Last Successful Live Verification:** `2026-11-19T12:42:50+05:30`.
