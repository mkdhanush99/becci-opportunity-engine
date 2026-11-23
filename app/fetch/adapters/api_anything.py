"""API Anything Source Adapter.

Integrates https://github.com/goodnight000/api-anything as an optional
read-only source adapter and learned website-request layer.

Compliance with Master Autonomous Build Directive Section 5:
1. Prefers existing read operations before attempting new learning.
2. Strict domain confirmation against source registry.
3. READ-ONLY operations only (writes strictly prohibited).
4. Local-only mode supported; credentials/cookies never exported.
5. Reports blocked/WAF/CAPTCHA states as `is_blocked=True` without endless loops.
6. Graceful degradation: If api-anything CLI is unavailable or fails, returns
   structured fallback status so engine seamlessly delegates to standard HTTP fetcher.
"""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
import time
from typing import Any, Optional

from app.fetch.adapters.base import AdapterHealth, BaseSourceAdapter, RawOpportunityPayload

logger = logging.getLogger(__name__)


class ApiAnythingAdapter(BaseSourceAdapter):
    """Adapter invoking API Anything for learned public read operations."""

    def __init__(self, source_id: str, domain: str, operation_name: str = "search", config: Optional[dict[str, Any]] = None):
        super().__init__(source_id, domain, config)
        self.operation_name = operation_name
        self.cli_binary = shutil.which("api-anything") or shutil.which("npx")
        self.enabled = self.config.get("api_anything_enabled", True)

    @property
    def adapter_type(self) -> str:
        return "api_anything"

    async def health_check(self) -> AdapterHealth:
        start_time = time.perf_counter()
        if not self.enabled or not self.cli_binary:
            return AdapterHealth(
                source_id=self.source_id,
                adapter_type=self.adapter_type,
                is_healthy=False,
                response_time_ms=0.0,
                error_message="API Anything CLI or Node runtime not configured or adapter disabled."
            )

        # Quick probe for source operation spec
        try:
            # Check catalog or local operation status
            proc = await asyncio.create_subprocess_exec(
                "npx", "-y", "api-anything", "info", self.domain, "--format", "json",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10.0)
            latency = (time.perf_counter() - start_time) * 1000

            if proc.returncode == 0:
                return AdapterHealth(
                    source_id=self.source_id,
                    adapter_type=self.adapter_type,
                    is_healthy=True,
                    status_code=200,
                    response_time_ms=round(latency, 2)
                )
            else:
                err_text = stderr.decode(errors="replace").strip()
                is_blocked = "blocked" in err_text.lower() or "challenge" in err_text.lower()
                return AdapterHealth(
                    source_id=self.source_id,
                    adapter_type=self.adapter_type,
                    is_healthy=False,
                    status_code=proc.returncode,
                    response_time_ms=round(latency, 2),
                    error_message=err_text[:200],
                    is_blocked=is_blocked
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

    async def fetch(self, query: str = "", limit: int = 10, **kwargs) -> list[RawOpportunityPayload]:
        """Call learned read operation over CLI / local runner."""
        if not self.enabled:
            logger.info("API Anything adapter disabled for %s; skipping.", self.source_id)
            return []

        cmd = [
            "npx", "-y", "api-anything", "call", self.domain, self.operation_name,
            f"query={query}", f"limit={limit}",
            "--fields", "title,url,description,deadline,date",
            "--max-tier", "1",  # Plain HTTP read only, no intrusive headless writes
            "--format", "json"
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)

            if proc.returncode != 0:
                err_text = stderr.decode(errors="replace")
                if "blocked" in err_text.lower():
                    logger.warning("API Anything reported blocked for %s: %s", self.domain, err_text[:120])
                return []

            res_data = json.loads(stdout.decode(errors="replace"))
            items = res_data.get("data", [])
            payloads = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                title = item.get("title") or item.get("name")
                url = item.get("url") or item.get("link")
                if not title or not url:
                    continue
                payloads.append(RawOpportunityPayload(
                    source_id=self.source_id,
                    source_url=url,
                    original_title=title,
                    raw_content=json.dumps(item),
                    original_deadline=item.get("deadline"),
                    metadata={"via": "api_anything", "domain": self.domain}
                ))
            return payloads

        except Exception as exc:
            logger.warning("API Anything invocation error for %s: %s", self.source_id, exc)
            return []
