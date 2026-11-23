"""Base Source Adapter Interface.

Defines the contract for all BECCI opportunity ingestion adapters,
providing an abstraction boundary so underlying mechanisms (official APIs,
plain HTTP scrapers, headless browsers, or learned request patterns via API Anything)
can be swapped, disabled, or tested independently without rewriting the engine.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


@dataclass
class RawOpportunityPayload:
    source_id: str
    source_url: str
    original_title: str
    raw_content: str
    category_hint: Optional[str] = None
    original_deadline: Optional[str] = None
    original_reference: Optional[str] = None
    document_urls: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    fetched_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class AdapterHealth:
    source_id: str
    adapter_type: str
    is_healthy: bool
    status_code: Optional[int] = None
    response_time_ms: float = 0.0
    error_message: Optional[str] = None
    is_blocked: bool = False
    checked_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class BaseSourceAdapter(abc.ABC):
    """Abstract Base Class for Source Adapters."""

    def __init__(self, source_id: str, domain: str, config: Optional[dict[str, Any]] = None):
        self.source_id = source_id
        self.domain = domain
        self.config = config or {}

    @property
    @abc.abstractmethod
    def adapter_type(self) -> str:
        """Returns adapter type identifier (e.g. 'official_api', 'http_scraper', 'api_anything')."""
        ...

    @abc.abstractmethod
    async def fetch(self, **kwargs) -> list[RawOpportunityPayload]:
        """Fetch raw opportunity payloads from the source."""
        ...

    @abc.abstractmethod
    async def health_check(self) -> AdapterHealth:
        """Probe the source health without fetching full payloads."""
        ...
