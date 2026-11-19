"""robots.txt policy checks. We never fetch a path disallowed for our user-agent."""
from __future__ import annotations

import time
import urllib.robotparser
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from app.config import get_settings


@dataclass
class RobotsDecision:
    allowed: bool
    reason: str
    robots_url: str
    crawl_delay: float | None = None


class RobotsCache:
    def __init__(self, ttl_seconds: int = 6 * 3600, client_factory=None):
        self.ttl = ttl_seconds
        self._cache: dict[str, tuple[float, urllib.robotparser.RobotFileParser | None, str]] = {}
        self._client_factory = client_factory

    def _load(self, origin: str) -> tuple[urllib.robotparser.RobotFileParser | None, str]:
        s = get_settings()
        robots_url = f"{origin}/robots.txt"
        rp = urllib.robotparser.RobotFileParser()
        factory = self._client_factory or (lambda: httpx.Client(timeout=15, follow_redirects=True,
                                                                headers={"User-Agent": s.user_agent}))
        try:
            with factory() as c:
                r = c.get(robots_url)
        except httpx.HTTPError as e:
            return None, f"robots.txt unreachable ({type(e).__name__}); treated as no restrictions declared"
        ctype = r.headers.get("content-type", "")
        if r.status_code in (401, 403):
            rp.parse(["User-agent: *", "Disallow: /"])
            return rp, f"robots.txt returned {r.status_code}; treating site as disallowing automated access"
        if r.status_code >= 400 or "html" in ctype.lower():
            # 404 / redirect to an HTML page: no robots policy published.
            return None, f"no robots.txt published (HTTP {r.status_code})"
        rp.parse(r.text.splitlines())
        return rp, "robots.txt parsed"

    def check(self, url: str) -> RobotsDecision:
        s = get_settings()
        p = urlparse(url)
        origin = f"{p.scheme}://{p.netloc}"
        now = time.monotonic()
        cached = self._cache.get(origin)
        if not cached or now - cached[0] > self.ttl:
            rp, note = self._load(origin)
            self._cache[origin] = (now, rp, note)
        else:
            _, rp, note = cached
        robots_url = f"{origin}/robots.txt"
        if rp is None:
            return RobotsDecision(True, note, robots_url)
        ok = rp.can_fetch(s.robots_user_agent, url)
        delay = rp.crawl_delay(s.robots_user_agent)
        return RobotsDecision(ok, note if ok else f"disallowed by robots.txt ({note})", robots_url,
                              float(delay) if delay else None)


robots_cache = RobotsCache()
