"""Research Orchestrator: Central execution engine for autonomous research agents.

Capabilities:
* Dispatches registered agents (JobScout, FundingScout, TenderScout).
* JobLock concurrency control prevents duplicate parallel scans on the same source.
* Exponential backoff retry for transient network failures (never retries BlockedError).
* Source-level failure isolation: a failed or blocked source never stops other healthy sources.
* Scheduled discovery runner (`run_due_scans`) and failure alerting (`get_source_alerts`).
"""
from __future__ import annotations

import datetime as dt
import time
import uuid
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.base import BaseAgent, ScanContext
from app.agents.funding_scout import FundingScout
from app.agents.job_scout import JobScout
from app.agents.tender_scout import TenderScout
from app.config import get_settings
from app.enums import ScanStatus, SourceSupport
from app.fetch.http_fetcher import BlockedError, FetchError
from app.models import AuditLog, JobLock, RawCapture, ScanRun, Source, utcnow
from app.pipeline.deduplication import handle_deduplication_and_changes
from app.pipeline.normalisation import normalise_item
from app.pipeline.verification import verify_opportunity

AGENTS: dict[str, BaseAgent] = {
    JobScout.agent_id: JobScout(),
    FundingScout.agent_id: FundingScout(),
    TenderScout.agent_id: TenderScout(),
}


def register_agent(agent: BaseAgent):
    AGENTS[agent.agent_id] = agent


class SourceLockedError(RuntimeError):
    """Raised when a scan is already running for the requested source."""


class Orchestrator:
    def __init__(self, session: Session):
        self.session = session
        self.settings = get_settings()

    def acquire_lock(self, lock_name: str, owner: str | None = None) -> str:
        now = utcnow()
        owner = owner or f"worker-{uuid.uuid4().hex[:8]}"
        existing = self.session.get(JobLock, lock_name)
        if existing:
            exp = existing.expires_at
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=dt.timezone.utc)
            if exp > now:
                raise SourceLockedError(f"Lock '{lock_name}' is held by {existing.owner} until {exp.isoformat()}")
            self.session.delete(existing)
            self.session.flush()

        lease = dt.timedelta(seconds=self.settings.lock_lease_seconds)
        lock = JobLock(name=lock_name, owner=owner, expires_at=now + lease)
        self.session.add(lock)
        self.session.commit()
        return owner

    def release_lock(self, lock_name: str, owner: str | None = None) -> None:
        existing = self.session.get(JobLock, lock_name)
        if existing and (owner is None or existing.owner == owner):
            self.session.delete(existing)
            self.session.commit()

    def run_source_scan(
        self,
        source_id: str,
        trigger: str = "manual",
        is_fixture: bool = False,
        capture_html: bool = True,
        max_attempts: int | None = None,
        backoff_base_seconds: float | None = None,
    ) -> ScanRun:
        source = self.session.get(Source, source_id)
        if not source:
            raise ValueError(f"Source '{source_id}' not found")

        agent = AGENTS.get(source.agent_id)
        if not agent:
            raise ValueError(f"No registered agent found for agent_id '{source.agent_id}'")

        lock_name = f"scan:{source.id}"
        owner = self.acquire_lock(lock_name)

        max_attempts = max_attempts if max_attempts is not None else 1
        backoff_base = backoff_base_seconds if backoff_base_seconds is not None else 1.0

        now = utcnow()
        scan_run = ScanRun(
            source_id=source.id,
            agent_id=source.agent_id,
            trigger=trigger,
            attempt=1,
            status=ScanStatus.RUNNING,
            started_at=now,
            is_fixture=is_fixture,
            log=[],
        )
        self.session.add(scan_run)
        self.session.commit()

        t_start = time.monotonic()
        try:
            for attempt in range(1, max_attempts + 1):
                scan_run.attempt = attempt
                captures: list[RawCapture] = []

                def on_capture(url: str, final_url: str, method: str, status: int | None, text: str):
                    if capture_html:
                        captures.append(
                            RawCapture(
                                scan_run_id=scan_run.id,
                                source_id=source.id,
                                url=url,
                                final_url=final_url,
                                method=method,
                                http_status=status,
                                content_hash="",
                                text_content=text[:100000],
                                fetched_at=utcnow(),
                            )
                        )

                ctx = ScanContext(source, capture=on_capture)
                try:
                    # 1. Agent Discovery & Extraction
                    extracted_items = agent.discover(source, ctx)
                    scan_run.items_seen = len(extracted_items)

                    new_count = 0
                    updated_count = 0
                    unchanged_count = 0
                    dup_count = 0
                    skipped_count = 0

                    # 2. Pipeline processing for each item
                    for item in extracted_items:
                        if item.skip_reason:
                            skipped_count += 1
                            continue

                        issues = agent.validate(item)
                        if issues:
                            ctx.step("item.validation_issues", key=item.external_key, issues=issues)

                        opp = normalise_item(item, source, agent.agent_id, is_fixture=is_fixture)

                        action, saved_opp = handle_deduplication_and_changes(
                            self.session, opp, actor=f"agent:{agent.agent_id}"
                        )
                        if action == "inserted":
                            new_count += 1
                            verify_opportunity(self.session, saved_opp, source)
                        elif action == "updated":
                            updated_count += 1
                            verify_opportunity(self.session, saved_opp, source)
                        elif action == "merged_duplicate":
                            dup_count += 1
                        else:
                            unchanged_count += 1

                    for c in captures:
                        self.session.add(c)

                    scan_run.items_new = new_count
                    scan_run.items_updated = updated_count
                    scan_run.items_unchanged = unchanged_count
                    scan_run.duplicates_detected = dup_count
                    scan_run.items_skipped = skipped_count
                    scan_run.status = ScanStatus.SUCCESS
                    scan_run.error = None
                    scan_run.pages_visited = ctx.pages_visited()
                    scan_run.log = ctx.log

                    fin = utcnow()
                    source.last_scan_at = fin
                    source.last_success_at = fin
                    source.consecutive_failures = 0
                    source.support_status = SourceSupport.SUPPORTED
                    source.next_scan_at = fin + dt.timedelta(minutes=source.scan_frequency_minutes)
                    break

                except BlockedError as e:
                    # Never retry access/policy blocks (robots.txt, 403, CAPTCHA, login wall)
                    scan_run.status = ScanStatus.BLOCKED
                    scan_run.error = str(e)
                    scan_run.pages_visited = ctx.pages_visited()
                    scan_run.log = ctx.log
                    fin = utcnow()
                    source.last_scan_at = fin
                    source.last_failure_at = fin
                    source.last_failure_reason = str(e)
                    source.consecutive_failures += 1
                    source.support_status = SourceSupport.UNSUPPORTED
                    self._record_failure_alert(source, ScanStatus.BLOCKED, str(e))
                    break

                except FetchError as e:
                    ctx.step("scan.transient_error", attempt=attempt, error=str(e)[:200])
                    if attempt < max_attempts:
                        delay = backoff_base * (2 ** (attempt - 1))
                        time.sleep(delay)
                        continue
                    scan_run.status = ScanStatus.FAILED
                    scan_run.error = f"{type(e).__name__}: {str(e)}"
                    scan_run.pages_visited = ctx.pages_visited()
                    scan_run.log = ctx.log
                    fin = utcnow()
                    source.last_scan_at = fin
                    source.last_failure_at = fin
                    source.last_failure_reason = str(e)
                    source.consecutive_failures += 1
                    source.next_scan_at = fin + dt.timedelta(minutes=max(15, source.scan_frequency_minutes // 4))
                    self._record_failure_alert(source, ScanStatus.FAILED, str(e))

                except Exception as e:
                    scan_run.status = ScanStatus.FAILED
                    scan_run.error = f"{type(e).__name__}: {str(e)}"
                    scan_run.pages_visited = ctx.pages_visited()
                    scan_run.log = ctx.log
                    fin = utcnow()
                    source.last_scan_at = fin
                    source.last_failure_at = fin
                    source.last_failure_reason = str(e)
                    source.consecutive_failures += 1
                    self._record_failure_alert(source, ScanStatus.FAILED, str(e))
                    break

                finally:
                    ctx.close()

        finally:
            t_end = time.monotonic()
            scan_run.finished_at = utcnow()
            scan_run.duration_seconds = round(t_end - t_start, 2)
            self.session.commit()
            self.release_lock(lock_name, owner)

        return scan_run

    def run_due_scans(
        self,
        *,
        category: str | None = None,
        force: bool = False,
        max_attempts: int = 2,
        backoff_base_seconds: float = 0.5,
    ) -> list[ScanRun]:
        """Executes scheduled discovery for all active due sources with per-source failure isolation."""
        now = utcnow()
        stmt = select(Source).where(Source.active.is_(True)).order_by(Source.id.asc())
        sources = self.session.scalars(stmt).all()
        runs: list[ScanRun] = []

        for src in sources:
            if category and category not in (src.categories or []):
                continue
            if not force and src.next_scan_at:
                nxt = src.next_scan_at
                if nxt.tzinfo is None:
                    nxt = nxt.replace(tzinfo=dt.timezone.utc)
                if nxt > now:
                    continue
            try:
                run = self.run_source_scan(
                    src.id,
                    trigger="schedule",
                    max_attempts=max_attempts,
                    backoff_base_seconds=backoff_base_seconds,
                )
                runs.append(run)
            except SourceLockedError:
                continue
            except Exception:
                # Isolate unexpected error so remaining sources continue
                continue
        return runs

    def get_source_alerts(self) -> list[dict]:
        """Returns structured health alerts for sources that have failed or are blocked."""
        stmt = select(Source).where(
            (Source.consecutive_failures > 0) | (Source.support_status == SourceSupport.UNSUPPORTED)
        )
        sources = self.session.scalars(stmt).all()
        alerts: list[dict] = []
        for s in sources:
            severity = "critical" if s.active and s.consecutive_failures >= 2 else (
                "warning" if s.consecutive_failures > 0 else "info"
            )
            alerts.append(
                {
                    "source_id": s.id,
                    "source_name": s.name,
                    "active": s.active,
                    "support_status": s.support_status,
                    "consecutive_failures": s.consecutive_failures,
                    "last_failure_at": s.last_failure_at.isoformat() if s.last_failure_at else None,
                    "reason": s.last_failure_reason or s.access_notes,
                    "severity": severity,
                }
            )
        return alerts

    def _record_failure_alert(self, source: Source, status: str, reason: str) -> None:
        self.session.add(
            AuditLog(
                actor="scheduler",
                action=f"source_scan_{status}",
                target_type="source",
                target_id=source.id,
                detail={
                    "consecutive_failures": source.consecutive_failures,
                    "reason": reason[:500],
                    "support_status": source.support_status,
                },
                created_at=utcnow(),
            )
        )
