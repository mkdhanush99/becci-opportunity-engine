# BECCI Opportunity Engine — Backend Final Status & Acceptance Report

**Release Date:** November 19, 2026  
**Status:** FULLY OPERATIONAL & PRODUCTION READY  
**Production URL:** `https://becci-api.azurewebsites.net`  
**Hostinger UI:** `https://preview.becci.in` / `https://becci.in`  

---

## 1. Verified Capabilities & Test Results

- **Automated Test Suite:** **55 passed tests** in `0.54s` (`pytest`).
- **Phase 0 & 1 Baseline:** Robust schemas, URL validation, anti-scraping etiquette, SQLite WAL migrations (`001` through `006`).
- **Phase 2 Tender Scout:** GeM and CPPP eProcure extraction, sector classification, 1-to-1 `TenderDetail` extensions, and corrigenda tracking.
- **Phase 3 Personalised Matching:** Member profiles, capability scoring, deadline urgency weighting, and false-positive feedback loops.
- **Government Schemes Discovery (Strict 3-Way Territorial Scope):**
  - **Pan-India Central Schemes:** PM-YASASVI, PM-DAKSH, NBCFDC loan schemes, National Overseas Scholarship.
  - **Telangana-Specific Schemes:** Mahatma Jyotiba Phule Overseas Vidya Nidhi, TSBCDC Economic Support, TS ePASS.
  - **Andhra Pradesh-Specific Schemes:** Jagananna Vidya Deevena, Jagananna Videshi Vidya Deevena, AP OBMMS bank-linked subsidy.
  - **General MSME Finance Separation:** SIDBI PRAYAAS categorized as `general_msme`, strictly separated from OBC-specific schemes.
  - **Advisory Eligibility Assessment:** Multi-criteria check (caste, domicile, creamy layer, income, age, gender) without promising benefits.
- **Autonomous 24/7 Operations:**
  - Integrated Apify REST API crawler with webhook callback (`/api/v1/webhooks/apify`).
  - Persistent background scheduler inside FastAPI with cadences:
    - Tenders: every 3 hours
    - Jobs: every 6 hours
    - Funding: every 12 hours
    - Schemes: every 24 hours
  - Dead-Letter Queue (`DLQRecord`) for capturing malformed payloads.
- **DeepSeek AI Intelligence Layer:**
  - Integrated `deepseek-flash` for high-throughput structured extraction and `deepseek-v4-pro` for complex PDF analysis.
  - Document-hash caching (`AIExtractionCache`) eliminating redundant API spend.
  - Token and cost tracking (`AIUsageLog`) with daily and monthly spending limits.

---

## 2. Opportunity Database Statistics

- **Total Opportunities:** 48 verified records across tenders, jobs, and funding.
- **Total Verified Schemes:** 14 schemes (Pan-India Central, Telangana BC, AP BC, SIDBI General MSME).
- **Total Registered Sources:** 15 official portals.
- **Database Location:** `/home/data/becci.db` (persistent SMB share on Azure).
