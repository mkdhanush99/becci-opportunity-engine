# BECCI Opportunity Engine — API Endpoint Reference

| Method | Endpoint | Purpose | Access Level | Auth Required |
|---|---|---|---|---|
| `GET` | `/api/v1/health` | Service health & version check | Public | No |
| `GET` | `/api/v1/metadata` | Category, state & sector lists | Public | No |
| `GET` | `/api/v1/opportunities` | Search & filter opportunities | Public | No |
| `GET` | `/api/v1/opportunities/{id}` | Inspect opportunity & evidence | Public | No |
| `GET` | `/api/v1/schemes` | List BC/OBC & MSME schemes | Public | No |
| `GET` | `/api/v1/schemes/{id}` | Detailed scheme guidelines | Public | No |
| `POST` | `/api/v1/schemes/{id}/check-eligibility` | Advisory eligibility assessment | Public | No |
| `POST` | `/api/v1/auth/register` | Member account creation | Public | No |
| `POST` | `/api/v1/auth/login` | Member login & JWT issue | Public | No |
| `GET` | `/api/v1/profile` | View business profile | Member | Bearer JWT |
| `PUT` | `/api/v1/profile` | Update business profile | Member | Bearer JWT |
| `GET` | `/api/v1/recommendations` | AI-matched recommendations | Member | Bearer JWT |
| `POST` | `/api/v1/saved/{id}` | Save/bookmark opportunity | Member | Bearer JWT |
| `GET` | `/api/v1/saved` | List saved opportunities | Member | Bearer JWT |
| `POST` | `/api/v1/webhooks/apify` | Ingest Apify crawler results | Webhook | Secret (Query/Header) |
| `POST` | `/api/admin/auth/login` | Administrator authentication | Public | No |
| `GET` | `/api/admin/queue` | Human review queue | Admin (Reviewer) | Bearer JWT |
| `POST` | `/api/admin/opportunities/{id}/review` | Approve/reject opportunity | Admin (Reviewer) | Bearer JWT |
| `GET` | `/api/admin/sources` | List all source registries | Admin (Viewer) | Bearer JWT |
| `POST` | `/api/admin/sources/{id}/toggle` | Toggle source active/paused | Admin (Admin) | Bearer JWT |
| `POST` | `/api/admin/sources/{id}/scan` | Trigger immediate scan | Admin (Admin) | Bearer JWT |
| `GET` | `/api/admin/scheduler/status` | Real-time scheduler cadences | Admin (Viewer) | Bearer JWT |
| `GET` | `/api/admin/dlq` | Dead-letter queue inspection | Admin (Viewer) | Bearer JWT |
| `GET` | `/api/admin/ai/metrics` | DeepSeek token & cost audit | Admin (Viewer) | Bearer JWT |
| `POST` | `/api/admin/apify/run-actor` | Launch Apify cloud crawler | Admin (Admin) | Bearer JWT |
