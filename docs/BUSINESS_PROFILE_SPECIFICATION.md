# BECCI Business Profile Specification

**Date:** 2026-11-19  
**Module:** `app/models.py` (`BusinessProfile`), `app/schemas.py`, `app/api/member.py`

---

## 1. Design Goals & Data Minimisation

The Business Profile captures **only** the structured attributes required to match a BECCI member against government tenders, funding schemes, vendor empanelments, innovation challenges, and relevant recruitment opportunities.

**Privacy & Commercial Sensitivity Rules:**
- **Do NOT collect** PAN numbers, Aadhaar numbers, bank account numbers, GSTIN strings, Udyam certificate numbers, tax returns, or home addresses.
- **Do NOT assume** every member has GST, Udyam, or corporate registration. All registration statuses explicitly support `not_registered`, `exempt`, `applied`, `not_applicable`, and `unknown`.
- **Optional financial/experience inputs:** `annual_turnover_lakhs` and `years_of_experience` are nullable. When omitted, the matching engine marks turnover/experience criteria as `details_to_confirm` rather than falsely marking the business `not_eligible`.

---

## 2. Field Specification

| Field | Type | Required | Controlled Values / Constraints | Matching Usage |
|---|---|---|---|---|
| `business_name` | `string(255)` | Yes | Non-empty display name | Profile identification |
| `business_type` | `BusinessType` enum | Yes | `manufacturer`, `trader_distributor`, `service_provider`, `contractor`, `startup`, `individual_entrepreneur`, `cooperative_shg`, `ngo_social_enterprise`, `other` | OEM/trader exclusion checks, funding/startup relevance, job relevance |
| `industry` | `string(128)` | No | Free-text sub-industry label (e.g., `"Cloud & Cybersecurity"`) | Keyword capability overlap |
| `becci_sector` | `BECCISector` enum | Yes | One of the 11 standard BECCI sectors | Primary sector match factor |
| `secondary_sectors` | `list[BECCISector]` | No | Up to 5 additional BECCI sectors | Secondary sector match factor |
| `state` | `string(64)` | Yes | Indian state/UT name (e.g., `"Telangana"`, `"Maharashtra"`) | Geographic relevance factor |
| `district` | `string(128)` | No | District or city name (e.g., `"Hyderabad"`, `"Pune"`) | District/local geographic boost |
| `business_stage` | `BusinessStage` enum | Yes | `idea_pre_revenue`, `early_stage`, `micro`, `small`, `medium`, `established` | Funding scheme & MSME programme alignment |
| `msme_udyam_status` | `RegistrationStatus` enum | Yes (default `unknown`) | `registered`, `applied`, `not_registered`, `not_applicable`, `unknown` | MSE purchase preference, EMD exemption, turnover/experience relaxation |
| `gst_status` | `GSTStatus` enum | Yes (default `unknown`) | `registered`, `exempt`, `not_registered`, `unknown` | Mandatory GST tender requirement check |
| `entity_type` | `EntityType` enum | Yes (default `sole_proprietorship`) | `unregistered_individual`, `sole_proprietorship`, `partnership`, `llp`, `private_limited`, `public_limited`, `opc`, `society_trust_cooperative`, `other` | Company/entity type eligibility |
| `annual_turnover_lakhs` | `float \| null` | No | `>= 0` (INR Lakhs, optional) | Compared against bidder turnover threshold (never confused with OEM turnover) |
| `years_of_experience` | `float \| null` | No | `>= 0` (years, optional) | Compared against past experience threshold |
| `licences_and_registrations` | `list[string]` | No | e.g., `["PAN", "ISO 9001", "GeM Seller", "FSSAI", "BIS", "OEM Authorization"]` | Checked against required registrations and licences |
| `capabilities` | `list[string]` | No | Core operational capabilities | Capability-to-scope text matching |
| `products_and_services` | `list[string]` | No | Specific goods/services supplied | Product/service keyword matching |
| `preferred_categories` | `list[Category]` | No | Default: `["tender", "funding", "job"]` | Opportunity category preference factor |

---

## 3. Access Control Rules

1. Each `MemberAccount` owns its own `BusinessProfile` (`member_id` foreign key with `UNIQUE` constraint).
2. `POST /api/v1/member/profile` and `PUT /api/v1/member/profile` operate exclusively on the authenticated member's profile.
3. `GET /api/v1/member/profile` returns `404` if not yet created and never accepts another member's ID.
4. Public APIs (`/api/v1/opportunities*`, `/api/v1/tenders*`) never join or expose `BusinessProfile`, `MemberAccount`, `SavedOpportunity`, or `OpportunityView`.
