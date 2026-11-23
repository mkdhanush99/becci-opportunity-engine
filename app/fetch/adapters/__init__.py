"""Source adapters package."""
from app.fetch.adapters.base import AdapterHealth, BaseSourceAdapter, RawOpportunityPayload
from app.fetch.adapters.api_anything import ApiAnythingAdapter
from app.fetch.adapters.official_api import OfficialApiAdapter
from app.fetch.adapters.registry import AdapterRegistry, adapter_registry

__all__ = [
    "BaseSourceAdapter",
    "AdapterHealth",
    "RawOpportunityPayload",
    "ApiAnythingAdapter",
    "OfficialApiAdapter",
    "AdapterRegistry",
    "adapter_registry",
]
