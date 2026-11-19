"""Tests for Apify REST API integration, Autonomous 24/7 Scheduler, and DLQ handling.

Verifies:
1. ApifyClient properties and error handling.
2. Apify Webhook ingestion pipeline:
   - Valid tenders / jobs ingested into database.
   - Scheme territorial guardrail (Pan-India, TG, AP accepted; unrelated state schemes rejected to DLQ).
   - Malformed records captured in DLQRecord.
3. Admin control endpoints:
   - GET /api/admin/scheduler/status
   - GET /api/admin/dlq
   - POST /api/admin/sources/{id}/toggle
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import session_scope
from app.fetch.apify_client import ApifyClient
from app.main import app
from app.models import DLQRecord, Opportunity, Source
from app.pipeline.apify_ingestion import ingest_apify_raw_items

client = TestClient(app)


def test_apify_client_config():
    client_inst = ApifyClient(api_token="test_token_12345")
    assert client_inst.is_configured is True
    assert client_inst.api_token == "test_token_12345"

    headers = client_inst._get_headers()
    assert headers["Authorization"] == "Bearer test_token_12345"


def test_apify_ingestion_valid_tender_and_job():
    raw_items = [
        {
            "id": "apify-gem-tender-9999",
            "title": "Supply of Enterprise Networking Equipment across India",
            "url": "https://gem.gov.in/tenders/9999",
            "category": "tender",
            "issuing_organisation": "Government e-Marketplace (GeM)",
            "estimated_value": "₹45.00 Lakh",
            "state": None,
        },
        {
            "id": "apify-upsc-job-8888",
            "title": "Recruitment of Assistant Engineers across Central Departments",
            "url": "https://upsc.gov.in/recruitment/8888",
            "category": "job",
            "issuing_organisation": "Union Public Service Commission (UPSC)",
            "state": None,
        },
    ]

    with session_scope() as session:
        stats = ingest_apify_raw_items(session, raw_items, source_id="apify-test-crawler")
        assert stats["ingested"] == 2
        assert stats["dlq"] == 0

        t = session.scalar(select(Opportunity).where(Opportunity.external_key == "apify-gem-tender-9999"))
        assert t is not None
        assert t.category == "tender"

        j = session.scalar(select(Opportunity).where(Opportunity.external_key == "apify-upsc-job-8888"))
        assert j is not None
        assert j.category == "job"


def test_apify_ingestion_scheme_territorial_guardrail():
    """Unrelated state schemes (e.g. Maharashtra, UP) must be sent to DLQ and NOT ingested."""
    raw_items = [
        {
            "id": "apify-scheme-tg-01",
            "title": "Telangana BC Special Artisan Support Initiative",
            "url": "https://telangana.gov.in/schemes/tg-01",
            "category": "funding",
            "geographical_scope": "telangana",
            "state": "Telangana",
        },
        {
            "id": "apify-scheme-mh-01",
            "title": "Maharashtra State BC Financial Scheme (Exclusively for MH Domicile)",
            "url": "https://maharashtra.gov.in/schemes/mh-01",
            "category": "funding",
            "geographical_scope": "maharashtra",
            "state": "Maharashtra",
        },
    ]

    with session_scope() as session:
        stats = ingest_apify_raw_items(session, raw_items, source_id="apify-schemes-test")
        assert stats["ingested"] == 1
        assert stats["dlq"] == 1

        # Verify Telangana scheme was saved
        tg_scheme = session.scalar(select(Opportunity).where(Opportunity.external_key == "apify-scheme-tg-01"))
        assert tg_scheme is not None

        # Verify Maharashtra scheme was NOT saved to opportunities, but recorded in DLQ
        mh_scheme = session.scalar(select(Opportunity).where(Opportunity.external_key == "apify-scheme-mh-01"))
        assert mh_scheme is None

        dlq = session.scalar(select(DLQRecord).where(DLQRecord.stage == "scheme_scope_guardrail"))
        assert dlq is not None
        assert "Maharashtra" in dlq.error_reason


def test_apify_ingestion_malformed_item_routes_to_dlq():
    """Items without title or URL must be routed to DLQ."""
    raw_items = [
        {
            "id": "malformed-1",
            "title": "",  # missing title
            "url": "https://example.com/test",
        },
        {
            "id": "malformed-2",
            "title": "Valid Looking Title for Tender",
            "url": "",  # missing url
        },
    ]

    with session_scope() as session:
        stats = ingest_apify_raw_items(session, raw_items, source_id="apify-malformed-test")
        assert stats["ingested"] == 0
        assert stats["dlq"] == 2

        dlq_items = session.scalars(
            select(DLQRecord).where(DLQRecord.source_id == "apify-malformed-test")
        ).all()
        assert len(dlq_items) == 2


def test_admin_scheduler_status_endpoint():
    # Login as admin
    login_res = client.post("/api/admin/auth/login", json={"username": "admin", "password": "BecciAdmin2026!"})
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    res = client.get("/api/admin/scheduler/status", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert "enabled" in data
    assert "cadences" in data
    assert "tenders" in data["cadences"]
    assert "jobs" in data["cadences"]
    assert "funding" in data["cadences"]
    assert "schemes" in data["cadences"]
    assert data["cadences"]["tenders"]["cadence_hours"] == 3
    assert data["cadences"]["jobs"]["cadence_hours"] == 6


def test_admin_dlq_endpoint():
    login_res = client.post("/api/admin/auth/login", json={"username": "admin", "password": "BecciAdmin2026!"})
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    res = client.get("/api/admin/dlq", headers=headers)
    assert res.status_code == 200
    items = res.json()
    assert isinstance(items, list)


def test_admin_source_toggle():
    login_res = client.post("/api/admin/auth/login", json={"username": "admin", "password": "BecciAdmin2026!"})
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Find a source
    sources_res = client.get("/api/admin/sources", headers=headers)
    assert sources_res.status_code == 200
    src = sources_res.json()[0]
    src_id = src["id"]
    initial_active = src["active"]

    # Toggle
    toggle_res = client.post(f"/api/admin/sources/{src_id}/toggle", headers=headers)
    assert toggle_res.status_code == 200
    assert toggle_res.json()["active"] == (not initial_active)

    # Toggle back
    toggle_res2 = client.post(f"/api/admin/sources/{src_id}/toggle", headers=headers)
    assert toggle_res2.status_code == 200
    assert toggle_res2.json()["active"] == initial_active
