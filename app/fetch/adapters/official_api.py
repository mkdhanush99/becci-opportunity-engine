"""Official API Source Adapter.

Directly fetches opportunities from official government REST APIs, RSS/Atom feeds,
and structured public endpoints (e.g. GeM, CPPP, National Career Service, National Scholarship Portal).
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

import httpx

from app.fetch.adapters.base import AdapterHealth, BaseSourceAdapter, RawOpportunityPayload

logger = logging.getLogger(__name__)


class OfficialApiAdapter(BaseSourceAdapter):
    """Direct HTTP/REST API adapter for authorized and open government feeds."""

    def __init__(self, source_id: str, domain: str, endpoint_url: str, config: Optional[dict[str, Any]] = None):
        super().__init__(source_id, domain, config)
        self.endpoint_url = endpoint_url
        self.timeout = float(self.config.get("timeout", 15.0))

    @property
    def adapter_type(self) -> str:
        return "official_api"

    async def health_check(self) -> AdapterHealth:
        start_time = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                resp = await client.get(self.endpoint_url, headers={"User-Agent": "BECCI-Engine/3.0.0 (Research & Discovery)"})
                latency = (time.perf_counter() - start_time) * 1000
                is_healthy = 200 <= resp.status_code < 400
                return AdapterHealth(
                    source_id=self.source_id,
                    adapter_type=self.adapter_type,
                    is_healthy=is_healthy,
                    status_code=resp.status_code,
                    response_time_ms=round(latency, 2),
                    error_message=None if is_healthy else f"HTTP {resp.status_code}",
                    is_blocked=resp.status_code in (401, 403, 429)
                )
        except Exception as exc:
            latency = (time.perf_counter() - start_time) * 1000
            return AdapterHealth(
                source_id=self.source_id,
                adapter_type=self.adapter_type,
                is_healthy=False,
                response_time_ms=round(latency, 2),
                error_message=str(exc)
            )

    async def fetch(self, **kwargs) -> list[RawOpportunityPayload]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                resp = await client.get(self.endpoint_url, headers={"User-Agent": "BECCI-Engine/3.0.0"})
                if resp.status_code != 200:
                    logger.warning("Failed official API fetch for %s: %s", self.source_id, resp.status_code)
                    return []

                content_type = resp.headers.get("content-type", "")
                payloads = []
                if "application/json" in content_type:
                    data = resp.json()
                    items = data if isinstance(data, list) else data.get("items", data.get("data", []))
                    for item in items:
                        if isinstance(item, dict):
                            title = item.get("title") or item.get("subject") or item.get("scheme_name")
                            url = item.get("url") or item.get("link") or self.endpoint_url
                            if title:
                                payloads.append(RawOpportunityPayload(
                                    source_id=self.source_id,
                                    source_url=url,
                                    original_title=title,
                                    raw_content=str(item),
                                    original_deadline=item.get("deadline") or item.get("end_date"),
                                    metadata={"via": "official_api", "domain": self.domain}
                                ))
                return payloads
        except Exception as exc:
            logger.error("Error in OfficialApiAdapter for %s: %s", self.source_id, exc)
            return []
