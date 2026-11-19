from fastapi.testclient import TestClient
from app.db import Base, get_engine, session_scope
from app.enums import LifecycleStatus, SourceReliability
from app.main import app
from app.models import Opportunity, Source, utcnow
from app.security.auth import seed_admin_user
from app.seeds.sources import seed_sources


client = TestClient(app)


def setup_module():
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    with session_scope() as session:
        seed_sources(session)
        seed_admin_user(session, username="admin", password="BecciAdmin2026!")


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


def test_admin_metrics():
    login_res = client.post("/api/admin/auth/login", json={"username": "admin", "password": "BecciAdmin2026!"})
    token = login_res.json()["access_token"]
    res = client.get("/api/admin/metrics", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    data = res.json()
    assert data["total_sources"] >= 4
    assert data["supported_sources"] >= 2
