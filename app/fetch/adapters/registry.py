"""Source Adapter Registry.

Factory and dispatcher resolving appropriate adapters by source type,
supporting safe fallbacks between Official API, Plain HTTP Scrapers, and API Anything.
"""
from __future__ import annotations

from typing import Any, Optional

from app.fetch.adapters.api_anything import ApiAnythingAdapter
from app.fetch.adapters.base import BaseSourceAdapter
from app.fetch.adapters.official_api import OfficialApiAdapter


class AdapterRegistry:
    """Registry managing source adapters."""

    def __init__(self):
        self._adapters: dict[str, BaseSourceAdapter] = {}

    def register(self, source_id: str, adapter: BaseSourceAdapter) -> None:
        self._adapters[source_id] = adapter

    def get_adapter(self, source_id: str, domain: str, adapter_type: str = "official_api", **kwargs) -> BaseSourceAdapter:
        if source_id in self._adapters:
            return self._adapters[source_id]

        if adapter_type == "api_anything":
            adapter = ApiAnythingAdapter(source_id=source_id, domain=domain, config=kwargs)
        elif adapter_type == "official_api":
            endpoint = kwargs.get("endpoint_url", f"https://{domain}/api/v1/feed")
            adapter = OfficialApiAdapter(source_id=source_id, domain=domain, endpoint_url=endpoint, config=kwargs)
        else:
            # Default to official API or safe fallback
            endpoint = kwargs.get("endpoint_url", f"https://{domain}")
            adapter = OfficialApiAdapter(source_id=source_id, domain=domain, endpoint_url=endpoint, config=kwargs)

        self._adapters[source_id] = adapter
        return adapter


# Global registry singleton
adapter_registry = AdapterRegistry()
