# BECCI Opportunity Engine — Phase 2 Acceptance Remediation Report

**Date:** 2026-11-19  
**Scope:** Resolution of all four non-blocking conditions identified in `docs/PHASE_2_ACCEPTANCE_AUDIT.md` (`APPROVED WITH CONDITIONS`)  
**Final Decision:** **ALL CONDITIONS RESOLVED — READY FOR PHASE 3**

---

## 1. Executive Summary

All four remediation conditions from the Phase 2 Independent Acceptance Audit have been implemented, unit-tested, and applied in-place to `data/becci.db` while preserving all **35 existing genuine opportunities**, all historical `evidence`, `scan_runs`, and `verification_records`, and all existing security and Agent 07 verification controls.

| # | Remediation Condition | Status | Affected Records Updated In-Place | Verification |
|---|---|---|---|---|
| 1 | IT Sector Keyword Classification (`SECTOR_RULES`) | **Resolved** | 3 SIDBI IT RFPs (`83faf037...`, `abb0ff24...`, `0a6237c9...`) | `IT and technology`, zero false positives |
| 2 | Product Category Precedence (`classify_sector`) | **Resolved** | GeM `GEM/2025/B/5894420` (`ecfe1d2c...`) | `IT and technology`, zero regressions across all 25 tenders |
| 3 | GeM PDF Bilingual Field Variants (`parse_gem_pdf_details`) | **Resolved** | GeM `GEM/2026/B/8055173` (`ee798019...`) + all 5 GeM `eligibility_intelligence` records | OEM vs Bidder turnover separated; `Organisation Name: N/a` rejected |
| 4 | SIDBI Challenge Fund Classification (`classify_sidbi_notice`) | **Resolved** | SIDBI Innovation Challenge Fund (`dd9dde49...`) | Routed to `funding` (`innovation_challenge`), `tender_details` row removed, all 5 evidence rows preserved |

---

## 2. Detailed Code & Extraction Changes

### Remediation 1 — IT Sector Keyword Classification (`app/agents/tender_scout.py`)
- Updated `BECCISector.IT_TECHNOLOGY` regex in `SECTOR_RULES` to support singular/plural and product-specific IT procurement terms:
  - `servers?`, `networks?`, `cameras?`, `computers?`, `laptops?`, `cyber\s*security`, `it\s+systems?`, `interactive\s+displays?`, `display\s+screens?`, `m365`, `microsoft\s+365`, `software\s+licens\w*`, `subscription\s+of\s+m365`, `technology\s+refresh`, `security\s+solutions?`, `information\s+security`.
- Kept physical security (`Hiring of Security Agency`) strictly under `Services` to prevent broad over-matching.

### Remediation 2 — Product Category Precedence (`app/agents/tender_scout.py`)
- Refactored `classify_sector(text, product_category="", tender_category="", *, title="", buyer_text="")` to evaluate context tiers in strict precedence order:
  1. `product_category`
  2. `title`
  3. `text` (technical description)
  4. `buyer_text` (buyer / ministry name)
  5. `tender_category` fallback (`Works` / `Services` / `Goods`)
- Updated all callers (`build_gem_item_from_doc`, `build_cppp_item`, `parse_sidbi_tender_rows`) to pass `title` and `buyer_text` separately so buyer ministry names cannot override product/item context.
- Added `miscellaneous\s+goods` to `BECCISector.TRADING_DISTRIBUTION` so CPPP record `TIFR/PD/SQ26-45/261757` (*Miscellaneous Goods* for Tata Institute of Fundamental Research) does not regress to `Education and training`.

### Remediation 3 — GeM PDF Bilingual Field Variants (`app/agents/tender_scout.py`)
- Updated `parse_gem_pdf_details()` to extract both turnover field variants independently without confusing OEM turnover with bidder turnover:
  - `Minimum Average Annual Turnover of the bidder (For the last 3 Financial Years)` → `bidder_turnover_requirement`
  - `OEM Average Turnover (Last 3 Years)` → `oem_turnover_requirement`
- Added explicit `turnover_field_variant` metadata (`bidder_average_annual_turnover`, `oem_average_turnover_3yr`, `both_bidder_and_oem_turnover`, or `None` when absent — never inferred).
- Persisted `bidder_turnover_conditions`, `oem_turnover_conditions`, and `turnover_field_variant` inside `extract_eligibility_intelligence()`.
- Hardened `Organisation Name` parsing to reject placeholder values (`N/a`, `NA`, `N.A.`, `Nil`, `None`, `Not Applicable`, masked `***`).

### Remediation 4 — SIDBI Challenge Fund Classification (`app/agents/tender_scout.py`, `app/pipeline/normalisation.py`)
- Added `classify_sidbi_notice(title: str) -> dict` with five explicit classification rules:
  1. `sarfaesi_auction` → excluded with documented `skip_reason`
  2. `innovation_challenge_fund` → routed to `category = "funding"`, `subcategory = "innovation_challenge"`
  3. `funding_application_announcement` → routed to `category = "funding"`, `subcategory = "funding_programme"`
  4. `vendor_empanelment` → `category = "tender"`, `tender_category = "Empanelment"`
  5. `procurement_rfp` → `category = "tender"`, `tender_category = "Services"` or `"Goods"`
  6. `ambiguous_sidbi_notice` → `category = "tender"`, `tender_status = "under_verification"`, `manual_review_required = True`, `ambiguous_flag = True`, preserving all source evidence
- Updated `normalise_item()` in `app/pipeline/normalisation.py` to honour `item.fields.get("routed_category")` and only attach a `TenderDetail` row when `opp.category == "tender"`.

---

## 3. Before-and-After Database Record Audit (`data/becci.db`)

All **35 genuine opportunities** were preserved in-place (zero deletions or recreations of opportunity records), with `OpportunityVersion` and `AuditLog` entries recorded and Agent 07 (`verify_opportunity`) re-executed on every modified record.

| Opportunity ID | Source | Reference / Title | Field Changed | Before | After | Agent 07 Status |
|---|---|---|---|---|---|---|
| `83faf0378e124a11b2f860818fbb82ce` | `sidbi-tenders` | Request for Proposal for Procurement of High-End Laptops | `industry` / `tender_detail.sector` | `Trading and distribution` | `IT and technology` | `official_confirmed` |
| `abb0ff24896d4045b719b6604e8ab8c0` | `sidbi-tenders` | Request for Proposal for Technology refresh of Security Solutions | `industry` / `tender_detail.sector` | `Trading and distribution` | `IT and technology` | `official_confirmed` |
| `0a6237c965c04d63b43cdf7f83bfb223` | `sidbi-tenders` | Renewal of Subscription of M365 Licenses | `industry` / `tender_detail.sector` | `Trading and distribution` | `IT and technology` | `official_confirmed` |
| `ecfe1d2cc2ae4d6585cd724b6ab9b464` | `gem-public-bids` | `GEM/2025/B/5894420`: Interactive Display Screen 86 inch | `industry` / `tender_detail.sector` | `Healthcare` | `IT and technology` | `official_confirmed` |
| `ee79801946724b60a19dc0d4fdae017a` | `gem-public-bids` | `GEM/2026/B/8055173`: LED Luminaire For Road And Street Lights | `turnover_requirement` / `evidence` | `Not stated` + bogus `N/a` org evidence | `OEM Average Turnover (Last 3 Years): 10 Lakh (s)` (`oem_average_turnover_3yr`); bogus `N/a` evidence removed | `official_confirmed` |
| `dd9dde49fdf94b128ed7128900dd396a` | `sidbi-tenders` | SIDBI Innovation Challenge Fund 2nd Cohort Applications Open | `category` / `subcategory` / `tender_detail` | `tender` / `goods` (`TenderDetail` present) | `funding` / `innovation_challenge` (`TenderDetail` removed; all 5 evidence rows preserved) | `official_confirmed` |

**Post-Remediation Production Database Inventory (`data/becci.db`):**
- Total `opportunities`: **35** (`24` tenders, `6` funding, `5` jobs)
- Total `tender_details`: **24** (all genuine procurement tenders)
- Remaining 29 opportunities: **0 regressions**

---

## 4. Regression Testing, Isolation & Server Verification

- **Pytest Suite:** `PYTHONPATH=. .venv/bin/pytest -v --cov=app --cov-report=term-missing`
  - **Result:** **34 passed, 0 failed** (including 4 new test functions covering all Remediation 1–4 cases)
  - **Coverage:** **74% overall**, **82% on `app/agents/tender_scout.py`**
  - **Isolation:** Confirmed isolated test database (`data/test_becci.db`); `data/becci.db` untouched by tests.
- **Restart & Live API Verification (`http://127.0.0.1:8000`):**
  - `GET /api/v1/health` → `200 OK` (`version: 2.0.0`)
  - `GET /api/v1/tenders` → `200 OK` (`3` published verified tenders; unpublished records remain isolated)
  - `GET /api/v1/opportunities` → `200 OK` (`3` published verified opportunities)
  - `GET /admin` → `200 OK`
  - `GET /docs` → `200 OK`

---

## 5. Final Verdict

**ALL CONDITIONS RESOLVED — READY FOR PHASE 3**
