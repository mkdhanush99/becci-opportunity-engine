# BECCI OPPORTUNITY ENGINE — PHASE 2
## TENDER SCOUT TEST EXECUTION & COVERAGE REPORT

**Date of Execution:** November 19, 2026  
**Test Runner:** `pytest 9.2.0` (`Python 3.12.13`, `cov-7.1.0`)  
**Isolated Test Database:** `sqlite:///./data/test_becci.db` (auto-created and unlinked via `tests/conftest.py`)  
**Production Database Integrity:** `data/becci.db` verified untouched by test fixtures  

---

## 1. Test Execution Summary

```text
============================= test session starts ==============================
platform darwin -- Python 3.12.13, pytest-9.2.0, pluggy-1.7.0
rootdir: /Users/dhanushmakam/.gemini/antigravity/scratch/becci-opportunity-engine
plugins: cov-7.1.0, anyio-4.16.0
collected 30 items

tests/test_api.py::test_public_health PASSED                             [  3%]
tests/test_api.py::test_public_never_exposes_unpublished PASSED          [  6%]
tests/test_api.py::test_admin_auth_and_publish_flow PASSED               [ 10%]
tests/test_api.py::test_public_filtering_and_metadata PASSED             [ 13%]
tests/test_deduplication.py::test_deduplication_exact_key_change_detection PASSED [ 16%]
tests/test_deduplication.py::test_deduplication_fuzzy_title_match PASSED [ 20%]
tests/test_extraction.py::test_clean_text PASSED                         [ 23%]
tests/test_extraction.py::test_parse_date PASSED                         [ 26%]
tests/test_extraction.py::test_find_dated_claims PASSED                  [ 30%]
tests/test_extraction.py::test_find_reference PASSED                     [ 33%]
tests/test_extraction.py::test_find_vacancies PASSED                     [ 36%]
tests/test_extraction.py::test_title_key PASSED                          [ 40%]
tests/test_security_urls.py::test_normalise_url PASSED                   [ 43%]
tests/test_security_urls.py::test_reject_credentials_in_url PASSED       [ 46%]
tests/test_security_urls.py::test_reject_non_http_schemes PASSED         [ 50%]
tests/test_security_urls.py::test_ssrf_protection_localhost PASSED       [ 53%]
tests/test_security_urls.py::test_domain_allowlist_enforcement PASSED    [ 56%]
tests/test_tender_scout.py::test_gem_extraction_with_pdf_and_missing_field_defaults PASSED [ 60%]
tests/test_tender_scout.py::test_cppp_home_and_detail_extraction PASSED  [ 63%]
tests/test_tender_scout.py::test_sidbi_tenders_filters_sarfaesi_auctions PASSED [ 66%]
tests/test_tender_scout.py::test_deadline_monitoring_states PASSED       [ 70%]
tests/test_tender_scout.py::test_corrigendum_extension_and_cancellation_lifecycle PASSED [ 73%]
tests/test_tender_scout.py::test_all_11_becci_sectors_classification PASSED [ 76%]
tests/test_tender_scout.py::test_geographic_and_eligibility_intelligence PASSED [ 80%]
tests/test_tender_scout.py::test_robots_txt_blocks_mahatenders_and_invalid_pdf_handling PASSED [ 83%]
tests/test_tender_scout.py::test_tender_public_and_admin_apis_and_migrations PASSED [ 86%]
tests/test_tender_scout.py::test_scheduler_locking_retry_and_failure_isolation PASSED [ 90%]
tests/test_tender_scout.py::test_phase1_agents_regression PASSED         [ 93%]
tests/test_verification.py::test_verify_opportunity_domain_and_evidence PASSED [ 96%]
tests/test_verification.py::test_verify_expired_opportunity PASSED       [100%]

======================== 30 passed, 1 warning in 14.06s ========================
```

- **Total Tests Executed:** 30
- **Tests Passed:** **30 (100%)**
- **Tests Failed:** **0**
- **Tests Skipped:** **0**
- **Statement Coverage:** **74% overall** (up from 61% in Phase 1)

---

## 2. Verification Matrix Across All 20 Required Audit Scenarios

| # | Required Test Area | Test Function(s) | Verification Outcome |
|---|---|---|---|
| **1** | Real source discovery | Live scans on `cppp-eprocure`, `gem-public-bids`, `sidbi-tenders` | **PASS** — Real tenders discovered from all 3 supported sources and verified in `data/becci.db`. |
| **2** | Tender extraction | `test_gem_extraction_with_pdf_and_missing_field_defaults`, `test_cppp_home_and_detail_extraction`, `test_sidbi_tenders_filters_sarfaesi_auctions` | **PASS** — Extracts Tender ID, Ref No, Ministry/Dept, Estimated Value, EMD, Fee, Pre-Bid Date, Opening/Closing Dates, and PDF text. |
| **3** | Missing field handling | `test_gem_extraction_with_pdf_and_missing_field_defaults` | **PASS** — Explicitly assigns `"Not published"` or `"Not stated"` when financial or eligibility fields are omitted. |
| **4** | Deadline parsing | `test_deadline_monitoring_states`, `test_parse_date` | **PASS** — Evaluates `upcoming`, `open`, `closing_soon`, `extended`, `cancelled`, `under_verification`, and `expired`. |
| **5** | Corrigendum handling | `test_corrigendum_extension_and_cancellation_lifecycle` | **PASS** — Matches existing tender by Reference No/Tender ID, extends deadline, sets `tender_status="extended"`, and appends `OpportunityVersion`. |
| **6** | Tender cancellation | `test_corrigendum_extension_and_cancellation_lifecycle` | **PASS** — Cancellation notice transitions `tender_status` to `"cancelled"`, `lifecycle_status` to `WITHDRAWN`, and `VerificationStatus.REMOVED`. |
| **7** | Deduplication | `test_deduplication_exact_key_change_detection`, `test_deduplication_fuzzy_title_match`, `test_corrigendum_extension_and_cancellation_lifecycle` | **PASS** — Deduplicates by external key, reference number, `tender_id`, and RapidFuzz title similarity. |
| **8** | Eligibility extraction | `test_geographic_and_eligibility_intelligence`, `test_gem_extraction_with_pdf_and_missing_field_defaults` | **PASS** — Extracts MSME relaxation, Udyam requirement, GST, PAN, OEM/Manufacturer clauses, turnover, experience, and JV permissions. |
| **9** | Sector classification | `test_all_11_becci_sectors_classification` | **PASS** — Deterministically maps tenders across all 11 BECCI sectors (`Manufacturing`, `IT and technology`, `Construction and infrastructure`, `Healthcare`, etc.). |
| **10** | Geographic classification | `test_geographic_and_eligibility_intelligence`, `test_cppp_home_and_detail_extraction` | **PASS** — Assigns `national`, `state`, `district`, or `local` and detects Indian states/cities (`Telangana`, `Maharashtra`, etc.). |
| **11** | Verification evidence | `test_tender_public_and_admin_apis_and_migrations`, `test_verify_opportunity_domain_and_evidence` | **PASS** — Agent 07 checks `tender_reference_consistency`, `tender_deadline_evidence`, `tender_corrigendum_and_status`, and `tender_eligibility_intelligence`. |
| **12** | SSRF protection | `test_ssrf_protection_localhost`, `test_reject_non_http_schemes`, `test_reject_credentials_in_url` | **PASS** — Blocks loopback, private IPs, `.local`/`.internal` hosts, and non-HTTP schemes. |
| **13** | `robots.txt` enforcement | `test_robots_txt_blocks_mahatenders_and_invalid_pdf_handling` | **PASS** — Enforces `Disallow: /` on `mahatenders.gov.in` and raises `BlockedError`. |
| **14** | Invalid file handling | `test_robots_txt_blocks_mahatenders_and_invalid_pdf_handling` | **PASS** — Corrupt/non-PDF bytes safely return `""` without raising unhandled exceptions. |
| **15** | API authorisation & filtering | `test_tender_public_and_admin_apis_and_migrations`, `test_admin_auth_and_publish_flow` | **PASS** — Validates `/api/v1/tenders` and `/api/admin/tenders` with state, sector, status, and keyword filters. |
| **16** | Database migrations | `test_tender_public_and_admin_apis_and_migrations` | **PASS** — Verifies `001_phase1_baseline` and `002_phase2_tender_details` in `schema_migrations`. |
| **17** | Test & production DB isolation | `test_tender_public_and_admin_apis_and_migrations` | **PASS** — Confirms test records in `data/test_becci.db` never appear in `data/becci.db`. |
| **18** | Source failure recovery | `test_scheduler_locking_retry_and_failure_isolation` | **PASS** — Transient `FetchError` recovers on retry attempt 2; failed sources are logged without halting healthy sources. |
| **19** | Scheduling & locking | `test_scheduler_locking_retry_and_failure_isolation` | **PASS** — `JobLock` raises `SourceLockedError` when an active lease exists for the same source. |
| **20** | Phase 1 regression | `test_phase1_agents_regression` + all 19 Phase 1 tests | **PASS** — All Phase 1 JobScout, FundingScout, Verification, Deduplication, Security, and API tests pass without regression. |
