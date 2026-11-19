"""Tests for DeepSeek AI Intelligence Layer, structured extraction, caching, and spend auditing."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.ai.deepseek_client import DeepSeekClient
from app.db import session_scope
from app.main import app
from app.models import AIExtractionCache, AIUsageLog, utcnow

client = TestClient(app)


def test_deepseek_cost_calculation():
    ds = DeepSeekClient(api_key="test_key")
    # Flash pricing: $0.14 / 1M prompt, $0.28 / 1M completion
    cost_flash = ds.calculate_cost("deepseek-flash", prompt_tokens=1000, completion_tokens=500)
    # (1000 * 0.14 + 500 * 0.28) / 1_000_000 = (140 + 140) / 1_000_000 = 0.00028
    assert cost_flash == 0.00028

    # Pro pricing: $0.55 / 1M prompt, $2.19 / 1M completion
    cost_pro = ds.calculate_cost("deepseek-v4-pro", prompt_tokens=1000, completion_tokens=500)
    # (1000 * 0.55 + 500 * 2.19) / 1_000_000 = (550 + 1095) / 1_000_000 = 0.001645
    assert cost_pro == 0.001645


def test_deepseek_caching_and_usage_logging():
    ds = DeepSeekClient(api_key="test_key")
    test_prompt = "Sample job posting text for Python Developer at Hyderabad"
    test_instruction = "Extract job details"

    with session_scope() as session:
        # Pre-seed cache
        import hashlib
        cache_key = hashlib.sha256(f"deepseek-flash:{test_instruction}:{test_prompt}".encode("utf-8")).hexdigest()
        fake_response = {
            "role": "Python Developer",
            "employer": "Tech Corp",
            "is_government_job": False,
            "location": "Hyderabad",
            "salary": "₹12-18 LPA",
        }
        session.add(
            AIExtractionCache(
                cache_key=cache_key,
                model="deepseek-flash",
                response_json=fake_response,
                created_at=utcnow(),
            )
        )
        session.commit()

        # Call extract_structured -> should hit cache without calling external API
        res = ds.extract_structured(
            test_prompt,
            test_instruction,
            agent_id="job-scout",
            session=session,
        )
        assert res == fake_response


def test_admin_ai_metrics_endpoint():
    login_res = client.post("/api/admin/auth/login", json={"username": "admin", "password": "BecciAdmin2026!"})
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    with session_scope() as session:
        session.add(
            AIUsageLog(
                agent_id="test-agent",
                model="deepseek-flash",
                prompt_tokens=450,
                completion_tokens=120,
                total_tokens=570,
                cost_usd=0.0001,
                created_at=utcnow(),
            )
        )
        session.commit()

    res = client.get("/api/admin/ai/metrics", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert "default_model" in data
    assert data["default_model"] == "deepseek-flash"
    assert "spent_today_usd" in data
    assert "daily_spend_limit_usd" in data
    assert data["daily_spend_limit_usd"] == 2.0
    assert "total_calls" in data
    assert data["total_calls"] >= 1
