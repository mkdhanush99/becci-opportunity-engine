import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_crawler_status_endpoint():
    res = client.get("/api/v1/crawler/status")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"
    assert "supported_sources" in data
    assert "recent_runs" in data
    assert "total_opportunities" in data
    assert data["total_opportunities"] > 0


def test_crawler_sources_endpoint():
    res = client.get("/api/v1/crawler/sources")
    assert res.status_code == 200
    data = res.json()
    assert "sources" in data
    assert len(data["sources"]) > 0
    first = data["sources"][0]
    assert "id" in first
    assert "support_status" in first
    assert "opportunities_ingested" in first


def test_crawler_trigger_missing_source():
    res = client.post("/api/v1/crawler/trigger?source_id=nonexistent-portal")
    assert res.status_code == 404
