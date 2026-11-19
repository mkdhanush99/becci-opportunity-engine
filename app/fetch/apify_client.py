"""Production-grade client for the Apify REST API v2.

Allows BECCI to autonomously execute cloud-based Apify Actors (e.g. web-scraper,
cheerio-scraper, playwright-scraper) for pan-India portals and consume dataset items
via polling or webhook callbacks.

Features:
- Bearer token authentication from environment / settings (never hardcoded)
- Asynchronous Actor execution with webhook delivery
- Synchronous short-run Actor execution with dataset retrieval
- Default dataset item streaming
- Robust error classification (Auth, RateLimit, Network, Execution)
"""
from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any
import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

APIFY_BASE_URL = "https://api.apify.com/v2"


class ApifyError(RuntimeError):
    """Base error for Apify API communication failures."""


class ApifyAuthError(ApifyError):
    """Raised when the Apify API token is invalid or missing."""


class ApifyRateLimitError(ApifyError):
    """Raised when Apify returns HTTP 429 Too Many Requests."""


class ApifyRunError(ApifyError):
    """Raised when an Actor run fails or aborts."""


class ApifyClient:
    def __init__(self, api_token: str | None = None, base_url: str = APIFY_BASE_URL):
        self.settings = get_settings()
        self.api_token = (
            api_token
            or os.environ.get("APIFY_API_TOKEN")
            or getattr(self.settings, "apify_api_token", "")
        ).strip()
        self.base_url = base_url.rstrip("/")

    @property
    def is_configured(self) -> bool:
        return bool(self.api_token)

    def _get_headers(self) -> dict[str, str]:
        if not self.api_token:
            raise ApifyAuthError("Apify API token is not configured. Set APIFY_API_TOKEN.")
        return {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "BECCI-OpportunityBot/3.0 (+https://becci.in)",
        }

    def start_actor_run(
        self,
        actor_id: str,
        run_input: dict[str, Any],
        *,
        timeout_secs: int | None = None,
        memory_mbytes: int | None = None,
        webhooks: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Runs an Actor asynchronously and immediately returns the run object.
        
        Args:
            actor_id: e.g. "apify/web-scraper" or "compass~google-maps-extractor"
            run_input: JSON serialisable input dict passed to the Actor
            timeout_secs: Max execution timeout in seconds
            memory_mbytes: Power of 2 memory (min 128)
            webhooks: Optional list of webhook definition dicts
        """
        url = f"{self.base_url}/actors/{actor_id}/runs"
        params: dict[str, Any] = {}
        if timeout_secs:
            params["timeout"] = timeout_secs
        if memory_mbytes:
            params["memory"] = memory_mbytes
        if webhooks:
            encoded_webhooks = base64.b64encode(json.dumps(webhooks).encode("utf-8")).decode("ascii")
            params["webhooks"] = encoded_webhooks

        headers = self._get_headers()
        try:
            with httpx.Client(timeout=30.0) as client:
                res = client.post(url, json=run_input, headers=headers, params=params)
                if res.status_code == 401:
                    raise ApifyAuthError(f"Apify authentication failed: {res.text}")
                if res.status_code == 429:
                    raise ApifyRateLimitError("Apify rate limit exceeded")
                if res.status_code >= 400:
                    raise ApifyError(f"Apify start actor failed ({res.status_code}): {res.text}")
                data = res.json().get("data", {})
                logger.info(
                    "Started Apify Actor run %s for actor %s (status: %s)",
                    data.get("id"),
                    actor_id,
                    data.get("status"),
                )
                return data
        except httpx.RequestError as exc:
            raise ApifyError(f"Network error connecting to Apify: {exc}") from exc

    def get_run(self, run_id: str) -> dict[str, Any]:
        """Retrieves details of an Actor run."""
        url = f"{self.base_url}/actor-runs/{run_id}"
        headers = self._get_headers()
        try:
            with httpx.Client(timeout=20.0) as client:
                res = client.get(url, headers=headers)
                if res.status_code >= 400:
                    raise ApifyError(f"Apify get run failed ({res.status_code}): {res.text}")
                return res.json().get("data", {})
        except httpx.RequestError as exc:
            raise ApifyError(f"Network error getting Apify run: {exc}") from exc

    def get_dataset_items(
        self,
        dataset_id: str,
        *,
        offset: int = 0,
        limit: int = 1000,
        clean: bool = True,
    ) -> list[dict[str, Any]]:
        """Fetches items from a dataset."""
        url = f"{self.base_url}/datasets/{dataset_id}/items"
        params: dict[str, Any] = {
            "offset": offset,
            "limit": limit,
            "clean": 1 if clean else 0,
            "format": "json",
        }
        headers = self._get_headers()
        try:
            with httpx.Client(timeout=45.0) as client:
                res = client.get(url, headers=headers, params=params)
                if res.status_code >= 400:
                    raise ApifyError(f"Apify get dataset items failed ({res.status_code}): {res.text}")
                items = res.json()
                if isinstance(items, list):
                    return items
                return []
        except httpx.RequestError as exc:
            raise ApifyError(f"Network error fetching Apify dataset items: {exc}") from exc

    def run_actor_sync(
        self,
        actor_id: str,
        run_input: dict[str, Any],
        *,
        timeout_secs: int = 60,
        memory_mbytes: int = 256,
    ) -> list[dict[str, Any]]:
        """Executes an Actor synchronously and returns dataset items directly upon completion."""
        url = f"{self.base_url}/acts/{actor_id}/run-sync-get-dataset-items"
        params = {"timeout": timeout_secs, "memory": memory_mbytes}
        headers = self._get_headers()
        try:
            with httpx.Client(timeout=float(timeout_secs + 15)) as client:
                res = client.post(url, json=run_input, headers=headers, params=params)
                if res.status_code >= 400:
                    raise ApifyError(f"Apify synchronous execution failed ({res.status_code}): {res.text}")
                items = res.json()
                if isinstance(items, list):
                    return items
                return []
        except httpx.RequestError as exc:
            raise ApifyError(f"Network error in Apify sync run: {exc}") from exc
