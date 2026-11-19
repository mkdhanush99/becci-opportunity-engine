import datetime as dt
from fastapi.testclient import TestClient
from app.db import session_scope
from app.enums import LifecycleStatus, SourceReliability
from app.main import app
from app.models import Opportunity, utcnow

client = TestClient(app)


def test_public_health():
    res = client.get("/api/v1/health")
    assert res.status_code == 200
    assert res.json()["status"] == "healthy"


def test_public_never_exposes_unpublished():
    with session_scope() as session:
        unpub = Opportunity(
            id="opp-unpub-1",
            external_key="unpub-key",
            slug="unpub-slug",
            title="Internal Candidate Notice",
            category="job",
            issuing_organisation="Test Org",
            publisher="Test Org",
            source_type=SourceReliability.OFFICIAL_GOVERNMENT,
            source_name="Test Org",
            original_url="https://test.gov.in/item",
            lifecycle_status=LifecycleStatus.NEEDS_HUMAN_REVIEW,  # NOT published!
            source_id="tgpsc-whats-new",
            agent_id="job_scout",
            content_fingerprint="fp1",
            title_fingerprint="fp2",
            raw_title="raw",
            raw_text="raw",
            extracted_at=utcnow(),
        )
        session.merge(unpub)

    # Call public API
    res = client.get("/api/v1/opportunities")
    assert res.status_code == 200
    ids = [item["id"] for item in res.json()["items"]]
    assert "opp-unpub-1" not in ids

    # Direct fetch by ID should be 404
    res_direct = client.get("/api/v1/opportunities/opp-unpub-1")
    assert res_direct.status_code == 404


def test_admin_auth_and_publish_flow():
    # 1. Login
    login_res = client.post("/api/admin/auth/login", json={"username": "admin", "password": "BecciAdmin2026!"})
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 2. Check Review Queue
    queue_res = client.get("/api/admin/queue", headers=headers)
    assert queue_res.status_code == 200
    queue_items = [i["id"] for i in queue_res.json()]
    assert "opp-unpub-1" in queue_items

    # 3. Publish via review action
    rev_res = client.post(
        "/api/admin/opportunities/opp-unpub-1/review",
        json={"action": "publish", "reason": "Verified and approved by administrator"},
        headers=headers,
    )
    assert rev_res.status_code == 200
    assert rev_res.json()["lifecycle_status"] == LifecycleStatus.PUBLISHED

    # 4. Now verify it shows up on public API!
    pub_res = client.get("/api/v1/opportunities/opp-unpub-1")
    assert pub_res.status_code == 200
    data = pub_res.json()
    assert data["id"] == "opp-unpub-1"
    assert "BECCI provides this information for discovery and awareness" in data["disclaimer"]


def test_public_filtering_and_metadata():
    with session_scope() as session:
        # Create published opportunities across categories and states
        opp_job = Opportunity(
            id="pub-job-telangana",
            external_key="pub-job-tg",
            slug="pub-job-tg",
            title="Statistical Officer Telangana",
            category="job",
            state="Telangana",
            issuing_organisation="TGPSC",
            publisher="TGPSC",
            source_type=SourceReliability.OFFICIAL_GOVERNMENT,
            source_name="TGPSC",
            original_url="https://tgpsc.gov.in/item1",
            lifecycle_status=LifecycleStatus.PUBLISHED,
            deadline=dt.date(2026, 12, 31),
            source_id="tgpsc-whats-new",
            agent_id="job_scout",
            content_fingerprint="fp-job",
            title_fingerprint="fp-job-t",
            raw_title="raw",
            raw_text="raw",
            extracted_at=utcnow(),
        )
        opp_fund = Opportunity(
            id="pub-fund-national",
            external_key="pub-fund-nat",
            slug="pub-fund-nat",
            title="MSME Credit Support Scheme",
            category="funding",
            state=None,  # National
            issuing_organisation="SIDBI",
            publisher="SIDBI",
            source_type=SourceReliability.OFFICIAL_GOVERNMENT,
            source_name="SIDBI",
            original_url="https://sidbi.in/item2",
            lifecycle_status=LifecycleStatus.PUBLISHED,
            deadline=dt.date(2026, 11, 25),  # Closing soon!
            source_id="sidbi-schemes",
            agent_id="funding_scout",
            content_fingerprint="fp-fund",
            title_fingerprint="fp-fund-t",
            raw_title="raw",
            raw_text="raw",
            extracted_at=utcnow(),
        )
        session.merge(opp_job)
        session.merge(opp_fund)

    # 1. Filter by category
    res_job = client.get("/api/v1/opportunities?category=job")
    assert res_job.status_code == 200
    job_ids = [i["id"] for i in res_job.json()["items"]]
    assert "pub-job-telangana" in job_ids
    assert "pub-fund-national" not in job_ids

    # 2. Filter by state
    res_state = client.get("/api/v1/opportunities?state=Telangana")
    assert res_state.status_code == 200
    state_ids = [i["id"] for i in res_state.json()["items"]]
    assert "pub-job-telangana" in state_ids

    # 3. Categories count
    res_cats = client.get("/api/v1/categories")
    assert res_cats.status_code == 200
    cat_map = {c["category"]: c["count"] for c in res_cats.json()}
    assert "job" in cat_map
    assert "funding" in cat_map

    # 4. Locations count
    res_locs = client.get("/api/v1/locations")
    assert res_locs.status_code == 200
    loc_names = [l["state"] for l in res_locs.json()]
    assert "Telangana" in loc_names

    # 5. Sources list
    res_sources = client.get("/api/v1/sources")
    assert res_sources.status_code == 200
    assert len(res_sources.json()) >= 4
