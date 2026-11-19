"""Agent framework: every specialised scout is an independent module built on BaseAgent."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

from app.fetch.browser import BrowserEngine
from app.fetch.http_fetcher import HttpFetcher
from app.models import Source
from app.pipeline.extraction import ExtractedItem


@dataclass
class AgentConfig:
    category: str
    mandatory_fields: list[str]
    max_items_per_scan: int = 50
    max_documents_per_scan: int = 5
    subcategories: list[str] = field(default_factory=list)


class ScanContext:
    """Per-scan tools handed to parsers: fetchers, a step logger, and capture hooks.

    Fetchers are created lazily and are restricted to the source's approved domains.
    """

    def __init__(self, source: Source, *, http: HttpFetcher | None = None, browser: BrowserEngine | None = None,
                 capture: Callable[[str, str, str, int | None, str], None] | None = None):
        self.source = source
        allowed = list({source.domain, *(source.official_domains or [])})
        self.allowed_domains = allowed
        self._http = http
        self._browser = browser
        self._capture = capture
        self.log: list[dict] = []
        self.t0 = time.monotonic()

    @property
    def http(self) -> HttpFetcher:
        if self._http is None:
            self._http = HttpFetcher(self.allowed_domains)
        return self._http

    @property
    def browser(self) -> BrowserEngine:
        if self._browser is None:
            self._browser = BrowserEngine(self.allowed_domains)
        return self._browser

    def step(self, msg: str, **data):
        self.log.append({"t": round(time.monotonic() - self.t0, 2), "msg": msg, **data})

    def capture(self, url: str, final_url: str, method: str, status: int | None, text: str):
        if self._capture:
            self._capture(url, final_url, method, status, text)

    def pages_visited(self) -> list[dict]:
        out = []
        if self._http:
            out += self._http.visited
        if self._browser:
            out += self._browser.visited
        return out

    def close(self):
        if self._http:
            self._http.close()


Parser = Callable[[Source, ScanContext], list[ExtractedItem]]


class BaseAgent:
    agent_id: str = "base"
    name: str = "Base agent"
    description: str = ""
    config: AgentConfig
    parsers: dict[str, Parser] = {}

    def discover(self, source: Source, ctx: ScanContext) -> list[ExtractedItem]:
        parser = self.parsers.get(source.parser)
        if not parser:
            raise ValueError(f"agent {self.agent_id} has no parser {source.parser!r}")
        ctx.step("discover.start", parser=source.parser, url=source.url)
        items = parser(source, ctx)
        ctx.step("discover.done", items=len(items))
        return items[: self.config.max_items_per_scan]

    def validate(self, item: ExtractedItem) -> list[str]:
        """Agent-specific validation rules. Returns a list of issues (empty = valid)."""
        issues = []
        for f in self.config.mandatory_fields:
            if f == "title" and not item.title:
                issues.append("missing title")
            elif f == "original_url" and not item.original_url:
                issues.append("missing original_url")
            elif f not in ("title", "original_url") and not item.fields.get(f):
                issues.append(f"missing {f}")
        if len(item.title) > 500:
            issues.append("title too long")
        return issues
