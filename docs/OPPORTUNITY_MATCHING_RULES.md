# BECCI Opportunity Matching & Ranking Rules

**Date:** 2026-11-19  
**Module:** `app/matching/engine.py`

---

## 1. Non-Negotiable Safety & Trust Rules

1. **No Publication Bypass:** Member recommendations evaluate **only** opportunities where `lifecycle_status IN ('published', 'updated', 'closing_soon')` and `is_fixture = False`.
2. **No High-Priority Expired or Unverified Records:**
   - Expired opportunities (`deadline < today`, `expiry_status = 'expired'`, or `tender_status IN ('expired', 'cancelled', 'closed')`) are excluded from active recommendations. When evaluated directly via single-opportunity inspection, they receive `score = 0.0`, `is_active_recommendation = False`, and `eligibility_status = 'not_eligible'`.
   - Unverified opportunities (`verification_status != 'official_confirmed'`) are excluded from high-priority active recommendations and flagged `requires_manual_review`.
3. **Never Claim Guaranteed Eligibility:** Every match response carries the explicit disclaimer:
   > *"Assessment is informational based on published source text; final eligibility is determined solely by the issuing authority."*

---

## 2. Controlled Eligibility Statuses

| Status | Meaning & Trigger Conditions |
|---|---|
| `likely_match` | Sector/capability aligns, zero hard disqualifiers, key stated conditions (GST, turnover, experience, OEM/trader rules) appear satisfied, and source eligibility is not marked ambiguous. |
| `partial_match` | Relevant opportunity where some conditions are satisfied, while one or more non-fatal requirements are missing (e.g., GST/Udyam not yet registered, or state differs) or need confirmation. |
| `not_eligible` | Hard disqualifier detected from official source text (e.g., opportunity is expired/cancelled; tender explicitly excludes traders and business is `trader_distributor`; business turnover or experience is explicitly below the published threshold without applicable MSE relaxation). |
| `insufficient_information` | Relevant opportunity, but either the business profile omitted needed data (e.g., turnover/experience/GST status is `unknown`/`null`) or the source did not publish enough structured eligibility detail to evaluate. |
| `requires_manual_review` | Source eligibility is flagged `ambiguous_flag = True` (e.g., `"As per ATC"`, `"As per Tender Document"`, or ambiguous SIDBI notice) or verification status is not `official_confirmed`. |

---

## 3. Eligibility Intelligence Output Structure

For every evaluated opportunity, the engine returns:
- `eligibility_status`: one of the five controlled statuses above
- `why_it_matches`: concise, evidence-grounded reasons why this opportunity fits the business
- `satisfied_conditions`: conditions explicitly satisfied by the profile (including MSE/Udyam relaxation benefits)
- `missing_requirements`: conditions not currently met by the profile
- `details_to_confirm`: conditions that require member or official-document confirmation
- `required_documents`: documents mentioned in the official source (`Udyam Certificate`, `GST Registration`, `PAN`, `BharatKosh Fee Receipt`, `OEM Authorization`, etc.)
- `disclaimer`: non-guarantee notice

---

## 4. Configurable Ranking Formula

The relevance score (`0.0` to `100.0`) is a weighted sum normalized by the sum of active weights in `matching_configs`:

| Factor | Default Weight | Scoring Logic (0.0 – 1.0) |
|---|---|---|
| **Sector & Capability Match** | `30.0` | Primary `becci_sector` exact match (`1.0`); `secondary_sectors` match (`0.75`); keyword overlap in `capabilities` / `products_and_services` / `industry` (`0.40`–`0.85`); unrelated sector with no overlap (`0.0`). |
| **Geographic Match** | `20.0` | Same state + matching district/city (`1.0`); same state (`0.90`); National (`state is None` or `location_type == 'national'`, `0.80`); different state (`0.15`). |
| **Eligibility Match** | `25.0` | `likely_match` (`1.0`); `partial_match` (`0.65`); `insufficient_information` (`0.55`); `requires_manual_review` (`0.50`); `not_eligible` (`0.0`). |
| **Deadline Urgency** | `10.0` | Closing in 1–7 days (`1.0`); 8–21 days (`0.85`); >21 days (`0.65`); no published deadline (`0.40`); expired (`0.0`). |
| **Category Preference** | `10.0` | Matches `preferred_categories` (`1.0`); not in `preferred_categories` (`0.20`). |
| **Source Verification** | `5.0` | `official_confirmed` (`1.0`); `official_found_details_not_fully_verified` (`0.50`); other (`0.0`). |

**Post-Score Guards:**
- If `eligibility_status == 'not_eligible'`, total score is capped at `<= 25.0` (and `0.0` if expired/cancelled).
- If sector score is `0.0` (incorrect/unrelated sector and zero capability overlap), total score is capped at `<= 35.0` so off-sector records never rank as top recommendations.
- Tie-breaking is deterministic: `(-relevance_score, deadline_asc_nulls_last, opportunity_id_asc)`.
