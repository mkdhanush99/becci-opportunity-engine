"""Research Orchestrator: Central execution engine for autonomous research agents."""
from __future__ import annotations

import time
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.funding_scout import FundingScout
from app.agents.job_scout import JobScout
from app.agents.base import BaseAgent, ScanContext
from app.enums import ScanStatus, SourceSupport
from app.fetch.http_fetcher import BlockedError
from app.models import RawCapture, ScanRun, Source, utcnow
from app.pipeline.deduplication import handle_deduplication_and_changes
from app.pipeline.normalisation import normalise_item
from app.pipeline.verification import verify_opportunity

AGENTS: dict[str, BaseAgent] = {
    JobScout.agent_id: JobScout(),
    FundingScout.agent_id: FundingScout(),
}


def register_agent(agent: BaseAgent):
    AGENTS[agent.agent_id] = agent


class Orchestrator:
    def __init__(self, session: Session):
        self.session = session

    def run_source_scan(
        self,
        source_id: str,
        trigger: str = "manual",
        is_fixture: bool = False,
        capture_html: bool = True
    ) -> ScanRun:
        source = self.session.get(Source, source_id)
        if not source:
            raise ValueError(f"Source '{source_id}' not found")

        agent = AGENTS.get(source.agent_id)
        if not agent:
            raise ValueError(f"No registered agent found for agent_id '{source.agent_id}'")

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
        t_start = time.monotonic()

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

                # Agent-level validation
                issues = agent.validate(item)
                if issues:
                    ctx.step("item.validation_issues", key=item.external_key, issues=issues)

                # Normalisation
                opp = normalise_item(item, source, agent.agent_id, is_fixture=is_fixture)

                # Deduplication & Change Detection
                action, saved_opp = handle_deduplication_and_changes(self.session, opp, actor=f"agent:{agent.agent_id}")
                if action == "inserted":
                    new_count += 1
                    # Verification
                    verify_opportunity(self.session, saved_opp, source)
                elif action == "updated":
                    updated_count += 1
                    verify_opportunity(self.session, saved_opp, source)
                elif action == "merged_duplicate":
                    dup_count += 1
                else:
                    unchanged_count += 1

            # Save captures
            for c in captures:
                self.session.add(c)

            # Update scan run record
            scan_run.items_new = new_count
            scan_run.items_updated = updated_count
            scan_run.items_unchanged = unchanged_count
            scan_run.duplicates_detected = dup_count
            scan_run.items_skipped = skipped_count
            scan_run.status = ScanStatus.SUCCESS
            scan_run.pages_visited = ctx.pages_visited()
            scan_run.log = ctx.log

            # Update source stats
            source.last_scan_at = utcnow()
            source.last_success_at = utcnow()
            source.consecutive_failures = 0
            source.support_status = SourceSupport.SUPPORTED

        except BlockedError as e:
            scan_run.status = ScanStatus.BLOCKED
            scan_run.error = str(e)
            scan_run.log = ctx.log
            source.last_scan_at = utcnow()
            source.last_failure_at = utcnow()
            source.last_failure_reason = str(e)
            source.consecutive_failures += 1
            source.support_status = SourceSupport.UNSUPPORTED

        except Exception as e:
            scan_run.status = ScanStatus.FAILED
            scan_run.error = f"{type(e).__name__}: {str(e)}"
            scan_run.log = ctx.log
            source.last_scan_at = utcnow()
            source.last_failure_at = utcnow()
            source.last_failure_reason = str(e)
            source.consecutive_failures += 1

        finally:
            ctx.close()
            t_end = time.monotonic()
            scan_run.finished_at = utcnow()
            scan_run.duration_seconds = round(t_end - t_start, 2)
            self.session.commit()

        return scan_run
