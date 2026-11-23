"""Browser automation engine (Playwright, headless Chromium).

* Bounded concurrency (global semaphore) - never unlimited parallel sessions.
* Fresh, isolated browser context per scan (no persisted cookies/storage, no credentials).
* Identifies itself honestly via the configured user agent.
* Main-frame navigation restricted to approved domains; every navigation re-validated.
* Downloads disabled; images/media/fonts not loaded (lighter on source servers).
* Pages' own scripts run inside the browser sandbox only to render public content. We never
  evaluate scripts taken from page content, and only read back the rendered DOM as data.
* robots.txt is checked before navigation; CAPTCHA/login walls stop the scan (BLOCKED).
"""
from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass

from app.config import get_settings
from app.fetch.http_fetcher import LOGIN_PATH, BlockedError, FetchError, detect_block
from app.fetch.robots import RobotsCache, robots_cache
from app.security.urls import UnsafeURLError, host_in, host_of, validate_fetch_url

_global_sem = threading.BoundedSemaphore(get_settings().browser_max_concurrency)


@dataclass
class RenderedPage:
    url: str
    final_url: str
    status: int | None
    html: str
    method: str = "browser"


class BrowserEngine:
    def __init__(self, allowed_domains: list[str], *, robots: RobotsCache | None = None, check_dns: bool = True):
        self.settings = get_settings()
        self.allowed = allowed_domains
        self.robots = robots or robots_cache
        self.check_dns = check_dns
        self.visited: list[dict] = []

    def _validate(self, url: str) -> str:
        try:
            u = validate_fetch_url(url, self.allowed if self.settings.enforce_domain_allowlist else None,
                                   check_dns=self.check_dns)
        except UnsafeURLError as e:
            raise BlockedError(f"URL rejected by security policy: {e}") from e
        d = self.robots.check(u)
        if not d.allowed:
            raise BlockedError(d.reason)
        return u

    def render(self, url: str, *, wait_for_selector: str | None = None, extra_wait_ms: int = 1000) -> RenderedPage:
        u = self._validate(url)
        acquired = _global_sem.acquire(timeout=self.settings.scan_execution_timeout_seconds)
        if not acquired:
            raise FetchError("browser concurrency limit reached; try later")
        try:
            try:
                # Handle cases where render() is called from within an active asyncio event loop
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None

                if loop and loop.is_running():
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                        return pool.submit(lambda: asyncio.run(self._render(u, wait_for_selector, extra_wait_ms))).result()
                else:
                    return asyncio.run(self._render(u, wait_for_selector, extra_wait_ms))
            except (Exception, ImportError, BaseException) as e:
                # Fallback to HttpFetcher when browser/playwright is unavailable or fails
                from app.fetch.http_fetcher import HttpFetcher
                fetcher = HttpFetcher(self.allowed, robots=self.robots, check_dns=self.check_dns)
                resp = fetcher.get(u)
                return RenderedPage(url=u, final_url=resp.final_url, status=resp.status, html=resp.text, method="http_fallback")
        finally:
            _global_sem.release()

    async def _render(self, url: str, selector: str | None, extra_wait_ms: int) -> RenderedPage:
        from playwright.async_api import Error as PWError
        from playwright.async_api import TimeoutError as PWTimeout
        from playwright.async_api import async_playwright

        s = self.settings
        started = time.monotonic()
        nav_violation: list[str] = []
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--disable-dev-shm-usage"])
            try:
                ctx = await browser.new_context(user_agent=s.user_agent, accept_downloads=False,
                                                java_script_enabled=True, service_workers="block",
                                                locale="en-IN")
                allowed = self.allowed

                async def route(route, request):
                    if request.resource_type in ("image", "media", "font"):
                        return await route.abort()
                    if request.is_navigation_request() and request.frame.parent_frame is None:
                        h = host_of(request.url)
                        if not host_in(h, allowed):
                            nav_violation.append(request.url)
                            return await route.abort()
                    return await route.continue_()

                await ctx.route("**/*", route)
                page = await ctx.new_page()
                page.set_default_timeout(s.browser_navigation_timeout_ms)
                try:
                    resp = await page.goto(url, wait_until="domcontentloaded",
                                           timeout=s.browser_navigation_timeout_ms)
                    if selector:
                        await page.wait_for_selector(selector, timeout=s.browser_navigation_timeout_ms)
                    else:
                        try:
                            await page.wait_for_load_state("networkidle", timeout=15_000)
                        except PWTimeout:
                            pass
                    if extra_wait_ms:
                        await page.wait_for_timeout(extra_wait_ms)
                except PWTimeout as e:
                    self._log(url, None, started, "timeout")
                    raise FetchError(f"browser timeout at {url}: {e}") from e
                except PWError as e:
                    self._log(url, None, started, str(e)[:200])
                    if nav_violation:
                        raise BlockedError(f"navigation to non-approved domain blocked: {nav_violation[0]}") from e
                    raise FetchError(f"browser error at {url}: {e}") from e
                final = page.url
                status = resp.status if resp else None
                html = await page.content()
                self._log(url, status, started)
                if nav_violation:
                    raise BlockedError(f"page attempted to navigate off approved domains: {nav_violation[0]}")
                if host_of(final) and not host_in(host_of(final), allowed):
                    raise BlockedError(f"redirected to non-approved domain {final}")
                if LOGIN_PATH.search(final):
                    raise BlockedError(f"redirected to login page {final}")
                reason = detect_block(status or 200, final, html)
                if reason:
                    raise BlockedError(reason)
                if status and status >= 500:
                    raise FetchError(f"server error HTTP {status}")
                return RenderedPage(url=url, final_url=final, status=status, html=html)
            finally:
                await browser.close()

    def _log(self, url, status, started, error=None):
        self.visited.append({"url": url, "status": status, "method": "browser",
                             "ms": int((time.monotonic() - started) * 1000), "error": error, "at": time.time()})
