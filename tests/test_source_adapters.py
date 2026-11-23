"""Tests for Source Adapters and API Anything abstraction boundary."""
import pytest
from app.fetch.adapters import ApiAnythingAdapter, OfficialApiAdapter, adapter_registry
from app.fetch.adapters.base import AdapterHealth, RawOpportunityPayload


def test_adapter_registry_resolution():
    adapter = adapter_registry.get_adapter(
        source_id="test-gem",
        domain="gem.gov.in",
        adapter_type="official_api"
    )
    assert isinstance(adapter, OfficialApiAdapter)
    assert adapter.source_id == "test-gem"
    assert adapter.domain == "gem.gov.in"
    assert adapter.adapter_type == "official_api"


def test_api_anything_adapter_configuration():
    adapter = ApiAnythingAdapter(
        source_id="test-portal",
        domain="eprocure.gov.in",
        operation_name="search_tenders",
        config={"api_anything_enabled": False}
    )
    assert adapter.adapter_type == "api_anything"
    assert adapter.domain == "eprocure.gov.in"
    assert adapter.operation_name == "search_tenders"
    assert adapter.enabled is False


def test_api_anything_disabled_fallback():
    import asyncio

    adapter = ApiAnythingAdapter(
        source_id="test-portal",
        domain="eprocure.gov.in",
        config={"api_anything_enabled": False}
    )
    results = asyncio.run(adapter.fetch(query="roads"))
    assert results == []

    health = asyncio.run(adapter.health_check())
    assert health.is_healthy is False
    assert "disabled" in health.error_message.lower()
