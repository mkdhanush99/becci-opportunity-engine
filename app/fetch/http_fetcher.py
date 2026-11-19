"""Polite HTTP fetcher.

Guarantees:
* Only http(s) URLs on approved source domains (SSRF + allowlist), validated on every redirect hop.
* robots.txt respected for our user agent.
* Per-domain minimum interval between requests (rate limiting ourselves).
* Response size cap.
* Access controls (401/403/429, CAPTCHA pages, login redirects) are detected and reported as BLOCKED.
  We never retry around them, rotate identity, or attempt to bypass them.
"""
from __future__ import annotations

import hashlib
import re
import threading
import time
from dataclasses import dataclass, field

import httpx

from app.config import get_settings
from app.fetch.robots import RobotsCache, robots_cache
from app.security.urls import UnsafeURLError, host_of, normalise_url, validate_fetch_url


class FetchError(Exception):
    """Transient or unexpected fetch failure (eligible for retry)."""


class BlockedError(Exception):
    """Access is restricted (robots, auth, captcha, WAF). Never retried automatically."""


CAPTCHA_MARKERS = re.compile(
    r"\b(g-recaptcha|hcaptcha|cf-turnstile|captcha-delivery|verify you are human|are you a robot|"
    r"cf-chl-|challenge-platform|altcha)\b", re.I)
LOGIN_PATH = re.compile(r"/(login|signin|sign-in|auth|sso)(/|\?|$)", re.I)


@dataclass
class FetchResult:
    url: str
    final_url: str
    status: int
    content_type: str
    body: bytes
    redirects: list[str] = field(default_factory=list)
    method: str = "http"

    @property
    def text(self) -> str:
        enc = "utf-8"
        m = re.search(r"charset=([\w-]+)", self.content_type or "", re.I)
        if m:
            enc = m.group(1)
        return self.body.decode(enc, errors="replace")

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.body).hexdigest()


class DomainThrottle:
    def __init__(self):
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, host: str, min_interval: float):
        with self._lock:
            now = time.monotonic()
            nxt = self._last.get(host, 0.0) + min_interval
            delay = max(0.0, nxt - now)
            self._last[host] = now + delay
        if delay:
            time.sleep(delay)


throttle = DomainThrottle()


def detect_block(status: int, final_url: str, body_text: str) -> str | None:
    if status in (401, 407):
        return f"authentication required (HTTP {status})"
    if status == 403:
        return "access denied (HTTP 403) - site restricts automated access"
    if status == 429:
        return "rate limited by site (HTTP 429)"
    if CAPTCHA_MARKERS.search(body_text[:200_000]):
        return "CAPTCHA / anti-bot challenge detected"
    return None


class HttpFetcher:
    def __init__(self, allowed_domains: list[str] | None, *, robots: RobotsCache | None = None,
                 transport: httpx.BaseTransport | None = None, check_dns: bool = True,
                 respect_robots: bool = True):
        s = get_settings()
        self.settings = s
        self.allowed = allowed_domains if s.enforce_domain_allowlist else None
        self.robots = robots or robots_cache
        self.check_dns = check_dns
        self.respect_robots = respect_robots
        self.client = httpx.Client(
            timeout=s.http_timeout_seconds, follow_redirects=False, transport=transport,
            headers={"User-Agent": s.user_agent, "Accept": "text/html,application/xhtml+xml,application/xml,"
                     "application/pdf;q=0.9,*/*;q=0.8", "Accept-Language": "en-IN,en;q=0.8"})
        self.visited: list[dict] = []

    def close(self):
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    def check_allowed(self, url: str) -> str:
        try:
            u = validate_fetch_url(url, self.allowed, check_dns=self.check_dns)
        except UnsafeURLError as e:
            raise BlockedError(f"URL rejected by security policy: {e}") from e
        if self.respect_robots:
            d = self.robots.check(u)
            if not d.allowed:
                raise BlockedError(d.reason)
        return u

    def get(self, url: str, *, max_bytes: int | None = None, allow_login_redirect: bool = False) -> FetchResult:
        s = self.settings
        max_bytes = max_bytes or s.max_response_bytes
        current = self.check_allowed(url)
        redirects: list[str] = []
        for _hop in range(s.max_redirects + 1):
            throttle.wait(host_of(current), s.per_domain_min_interval_seconds)
            started = time.monotonic()
            try:
                with self.client.stream("GET", current) as r:
                    chunks, total = [], 0
                    for chunk in r.iter_bytes():
                        total += len(chunk)
                        if total > max_bytes:
                            raise FetchError(f"response exceeds {max_bytes} bytes")
                        chunks.append(chunk)
                    body = b"".join(chunks)
                    status, headers = r.status_code, r.headers
            except httpx.TimeoutException as e:
                self._log(current, None, started, f"timeout: {e}")
                raise FetchError(f"timeout fetching {current}") from e
            except httpx.HTTPError as e:
                self._log(current, None, started, f"{type(e).__name__}: {e}")
                raise FetchError(f"{type(e).__name__} fetching {current}: {e}") from e
            self._log(current, status, started)
            if status in (301, 302, 303, 307, 308) and "location" in headers:
                nxt = normalise_url(headers["location"], current)
                if LOGIN_PATH.search(nxt) and not allow_login_redirect:
                    raise BlockedError(f"redirected to a login page ({nxt}); not following")
                redirects.append(nxt)
                current = self.check_allowed(nxt)  # every hop re-validated (redirect / SSRF protection)
                continue
            ctype = headers.get("content-type", "")
            text_probe = body[:200_000].decode("utf-8", errors="ignore") if "html" in ctype or not ctype else ""
            reason = detect_block(status, current, text_probe)
            if reason:
                raise BlockedError(reason)
            if status >= 500:
                raise FetchError(f"server error HTTP {status} at {current}")
            return FetchResult(url=url, final_url=current, status=status, content_type=ctype, body=body,
                               redirects=redirects)
        raise FetchError(f"too many redirects from {url}")

    def _log(self, url, status, started, error=None):
        self.visited.append({"url": url, "status": status, "method": "http",
                             "ms": int((time.monotonic() - started) * 1000), "error": error,
                             "at": time.time()})
