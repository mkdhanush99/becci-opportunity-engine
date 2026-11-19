# BECCI OPPORTUNITY INTELLIGENCE ENGINE — API HANDOVER FOR PUBLIC WEBSITE

**Production Base URL:** `https://becci-api.azurewebsites.net`  
**Hostinger UI:** `https://preview.becci.in` / `https://becci.in`  
**Environment:** Azure App Service (Plan B1, Linux Python 3.12, Central India, Always-On)

---

## 1. System Architecture & High-Level Scope

The BECCI Opportunity Intelligence Engine is an autonomous opportunity discovery, verification, and personalized matching engine designed specifically for the Bahujan Entrepreneurs Chamber for Commerce & Industry (BECCI).

### Geographical Scope Rules
1. **Pan-India Tenders:** Procurement notices from GeM, CPPP eProcure, Railways, Defence, and PSUs across all of India.
2. **Pan-India Government & Private Jobs:** Recruitment notices from UPSC, SSC, Banking, Central/State recruitment boards, and verified employer career pages across all of India.
3. **Funding (Pan-India):** Institutional MSME financing (SIDBI General MSME), NBCFDC, and MSME Ministry loan initiatives.
4. **Government Schemes (Strict 3-Way Territorial Boundary):**
   - **Pan-India BC/OBC Schemes:** Central government schemes accessible to eligible applicants from Telangana and Andhra Pradesh.
   - **Telangana-Specific Schemes:** Exclusive to eligible residents of Telangana.
   - **Andhra Pradesh-Specific Schemes:** Exclusive to eligible residents of Andhra Pradesh.
   - *Schemes exclusive to unrelated states (e.g., Maharashtra, UP, Karnataka) are strictly filtered out.*

---

## 2. Public Endpoints (No Authentication Required)

### 2.1 Health & Metadata
- **`GET /api/v1/health`**
  - Returns service status, UTC timestamp, and version `3.0.0`.
  - Response:
    ```json
    {
      "status": "healthy",
      "timestamp": "2026-11-19T12:20:00Z",
      "version": "3.0.0"
    }
    ```

- **`GET /api/v1/metadata`**
  - Returns available categories, subcategories, states, and BECCI sectors.

### 2.2 Opportunities Discovery
- **`GET /api/v1/opportunities`**
  - Query Parameters:
    - `category`: `tender` | `job` | `funding`
    - `state`: e.g. `Telangana`, `Andhra Pradesh`
    - `q`: Free-text search string
    - `sector`: BECCI sector (e.g. `Healthcare`, `IT / Technology`, `Manufacturing`)
    - `page`: default `1`
    - `page_size`: default `20` (max 100)
    - `sort_by`: `published_date` | `deadline` | `relevance`

- **`GET /api/v1/opportunities/{id}`**
  - Returns full opportunity detail, evidence snippet, official source link, and verification status.

### 2.3 Government Schemes & Advisory Assessment
- **`GET /api/v1/schemes`**
  - Query Parameters:
    - `state`: `Telangana` | `Andhra Pradesh` (enforces strict 3-way boundary: shows Pan-India + Selected State schemes only).
    - `scope`: `pan_india` | `telangana` | `andhra_pradesh`
    - `classification`: `obc_bc_specific` | `general_msme` | `students` | `women_entrepreneurs` | `artisans`
    - `application_status`: `open` | `upcoming` | `closed` | `continuous`
- **`GET /api/v1/schemes/{id}`**
  - Returns scheme details including `applicable_castes`, `income_limit`, `benefit_type`, and official guidelines URL.
- **`POST /api/v1/schemes/{id}/check-eligibility`**
  - Advisory evaluation engine (never promises benefits or guarantees approval).
  - Request Body:
    ```json
    {
      "domicile_state": "Telangana",
      "caste_community": "OBC",
      "is_non_creamy_layer": true,
      "annual_family_income": 200000,
      "age": 28,
      "gender": "female"
    }
    ```
  - Response:
    ```json
    {
      "scheme_id": "...",
      "status": "likely_eligible",
      "summary": "You appear to meet the key published criteria.",
      "reasons": ["OBC community eligible", "Income within limit"],
      "missing_criteria": [],
      "disclaimer": "Advisory evaluation only. Official verification is required by the issuing authority."
    }
    ```

---

## 3. Member & Profile Matching Endpoints

- **`POST /api/v1/auth/register`**: Member registration (email, password).
- **`POST /api/v1/auth/login`**: Returns JWT Bearer token.
- **`GET /api/v1/profile`**: Get member business profile.
- **`PUT /api/v1/profile`**: Update sector, turnover, state, capabilities, and registrations.
- **`GET /api/v1/recommendations`**: AI-weighted personalized recommendations based on profile match.
- **`POST /api/v1/saved/{id}`**: Bookmark opportunity.
- **`GET /api/v1/saved`**: List bookmarked opportunities.

---

## 4. Autonomous Crawler & AI Layer Integration

1. **Apify REST Webhook (`POST /api/v1/webhooks/apify`):**
   - Ingests crawled datasets from cloud Apify actors (`web-scraper`, `cheerio-scraper`).
   - Validates schema and routes malformed payloads to Dead-Letter Queue (`DLQRecord`).
2. **DeepSeek AI Intelligence Layer:**
   - Powered by `deepseek-flash` for high-throughput structured extraction.
   - Document-hash caching (`AIExtractionCache`) eliminates redundant token spend.
   - Usage and cost tracked per-agent in `AIUsageLog`.
