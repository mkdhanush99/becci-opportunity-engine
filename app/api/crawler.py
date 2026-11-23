"""Crawler & Autonomous Discovery API: Real-time scan execution, telemetry, and source controls."""
from __future__ import annotations

import asyncio
import datetime as dt
import time
from typing import Any
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db, session_scope
from app.enums import ScanStatus, SourceSupport
from app.models import Opportunity, ScanRun, Source, utcnow
from app.orchestrator.scheduler import AutonomousScheduler, _LAST_RUNS, _RUNNING
from app.orchestrator.service import Orchestrator, SourceLockedError

router = APIRouter(prefix="/api/v1/crawler", tags=["Crawler & Autonomous Scouts"])


class TriggerCrawlRequest(BaseModel):
    source_id: str = "all"
    force: bool = False
    is_fixture: bool = False


class ScanRunSummary(BaseModel):
    id: str
    source_id: str
    agent_id: str
    trigger: str
    status: str
    items_seen: int
    items_new: int
    items_updated: int
    items_unchanged: int
    items_skipped: int
    duplicates_detected: int
    started_at: str | None
    finished_at: str | None
    duration_seconds: float | None
    error: str | None
    log: list[dict[str, Any]] = []


class CrawlerStatusResponse(BaseModel):
    status: str
    is_running: bool
    scheduler: dict[str, Any]
    supported_sources: list[str]
    recent_runs: list[ScanRunSummary]
    total_opportunities: int
    timestamp: str


def _format_scan_run(r: ScanRun) -> ScanRunSummary:
    dur = None
    if r.started_at and r.finished_at:
        dur = round((r.finished_at - r.started_at).total_seconds(), 2)
    return ScanRunSummary(
        id=r.id,
        source_id=r.source_id,
        agent_id=r.agent_id,
        trigger=r.trigger,
        status=r.status.value if hasattr(r.status, "value") else str(r.status),
        items_seen=r.items_seen or 0,
        items_new=r.items_new or 0,
        items_updated=r.items_updated or 0,
        items_unchanged=r.items_unchanged or 0,
        items_skipped=r.items_skipped or 0,
        duplicates_detected=r.duplicates_detected or 0,
        started_at=r.started_at.isoformat() if r.started_at else None,
        finished_at=r.finished_at.isoformat() if r.finished_at else None,
        duration_seconds=dur,
        error=r.error,
        log=r.log or [],
    )


@router.get("/status", response_model=CrawlerStatusResponse, summary="Get real-time crawler & scheduler status")
def get_crawler_status(session: Session = Depends(get_db)):
    sched = AutonomousScheduler()
    sched_info = sched.get_status()

    # Supported sources
    supported = session.scalars(
        select(Source.id).where(Source.support_status == SourceSupport.SUPPORTED, Source.active.is_(True))
    ).all()

    # Recent scan runs
    runs = session.scalars(
        select(ScanRun).order_by(ScanRun.started_at.desc()).limit(15)
    ).all()

    total_opps = session.scalar(select(func.count(Opportunity.id))) or 0

    return CrawlerStatusResponse(
        status="healthy",
        is_running=_RUNNING,
        scheduler=sched_info,
        supported_sources=list(supported),
        recent_runs=[_format_scan_run(r) for r in runs],
        total_opportunities=total_opps,
        timestamp=utcnow().isoformat(),
    )


@router.get("/sources", summary="List crawler sources with live health telemetry")
def list_crawler_sources(session: Session = Depends(get_db)):
    sources = session.scalars(select(Source).order_by(Source.id)).all()
    results = []
    for s in sources:
        # Count opportunities from this source
        opp_count = session.scalar(
            select(func.count(Opportunity.id)).where(Opportunity.source_id == s.id)
        ) or 0
        results.append({
            "id": s.id,
            "name": s.name,
            "url": s.url,
            "agent_id": s.agent_id,
            "categories": s.categories or [],
            "reliability": s.reliability,
            "support_status": s.support_status.value if hasattr(s.support_status, "value") else str(s.support_status),
            "scan_frequency_minutes": s.scan_frequency_minutes,
            "last_scan_at": s.last_scan_at.isoformat() if s.last_scan_at else None,
            "last_success_at": s.last_success_at.isoformat() if s.last_success_at else None,
            "last_failure_at": s.last_failure_at.isoformat() if s.last_failure_at else None,
            "last_failure_reason": s.last_failure_reason,
            "consecutive_failures": s.consecutive_failures,
            "opportunities_ingested": opp_count,
        })
    return {"sources": results, "total": len(results)}


@router.post("/trigger", summary="Trigger live crawler on demand")
def trigger_crawler(
    req: TriggerCrawlRequest | None = None,
    source_id: str | None = Query(None, description="Source ID to scan (or 'all')"),
    force: bool = Query(False, description="Force run even if locked/frequency not elapsed"),
    background: bool = Query(False, description="Run asynchronously in background"),
    session: Session = Depends(get_db),
):
    target_source = (req.source_id if req else None) or source_id or "all"
    is_force = (req.force if req else False) or force

    orchestrator = Orchestrator(session)

    if target_source == "all":
        # Discover all supported active sources
        supported_sources = session.scalars(
            select(Source).where(Source.support_status == SourceSupport.SUPPORTED, Source.active.is_(True))
        ).all()

        if not supported_sources:
            return {"status": "no_supported_sources", "scans": []}

        executed_runs = []
        for s in supported_sources:
            try:
                run = orchestrator.run_source_scan(
                    source_id=s.id,
                    trigger="api:dashboard_manual",
                    is_fixture=False,
                )
                executed_runs.append(_format_scan_run(run))
            except SourceLockedError:
                continue
            except Exception as e:
                executed_runs.append({
                    "source_id": s.id,
                    "status": "failed",
                    "error": str(e),
                })
        return {
            "status": "completed",
            "trigger": "all_sources",
            "scanned_count": len(executed_runs),
            "scans": executed_runs,
        }
    else:
        # Scan single requested source
        source = session.get(Source, target_source)
        if not source:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Source '{target_source}' not found")

        try:
            run = orchestrator.run_source_scan(
                source_id=target_source,
                trigger="api:dashboard_manual",
                is_fixture=False,
            )
            return {
                "status": "completed",
                "source_id": target_source,
                "scan": _format_scan_run(run),
            }
        except SourceLockedError as e:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Crawl execution error: {e}") from e


@router.get("/runs/{run_id}", summary="Get detailed scan run log and metadata")
def get_scan_run(run_id: str, session: Session = Depends(get_db)):
    run = session.get(ScanRun, run_id)
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Scan run '{run_id}' not found")
    return _format_scan_run(run)
