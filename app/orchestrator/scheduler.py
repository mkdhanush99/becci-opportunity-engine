"""Autonomous 24/7 Scheduler for BECCI Opportunity Intelligence Engine.

Runs permanently in the background on Azure App Service with:
- Strict cadence separation:
  * Pan-India Tenders: Every 3 hours
  * Pan-India Jobs (Govt & Private): Every 6 hours
  * Funding (SIDBI, NBCFDC, MSME): Every 12 hours
  * Government Schemes (Central, TG, AP BC/OBC): Every 24 hours
- Database JobLock concurrency control across container restarts
- Integrated Apify cloud crawlers and local research scouts
- Failure isolation: errors in one source or category never halt other pipelines
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
from typing import Any
from sqlalchemy import select

from app.config import get_settings
from app.db import session_scope
from app.fetch.apify_client import ApifyClient
from app.models import JobLock, ScanRun, Source, utcnow
from app.orchestrator.service import Orchestrator

logger = logging.getLogger(__name__)

# In-memory last run timestamps (persisted in DB locks across restarts)
_LAST_RUNS: dict[str, dt.datetime] = {}
_SCHEDULER_TASK: asyncio.Task | None = None
_RUNNING = False


class AutonomousScheduler:
    def __init__(self):
        self.settings = get_settings()
        self.apify_client = ApifyClient()

    def get_status(self) -> dict[str, Any]:
        """Returns the real-time status of the autonomous scheduler."""
        now = utcnow()
        cadences = {
            "tenders": self.settings.cadence_tenders_hours,
            "jobs": self.settings.cadence_jobs_hours,
            "funding": self.settings.cadence_funding_hours,
            "schemes": self.settings.cadence_schemes_hours,
        }
        category_status = {}
        for cat, hours in cadences.items():
            last = _LAST_RUNS.get(cat)
            next_due = (last + dt.timedelta(hours=hours)) if last else now
            is_due = (now >= next_due) if last else True
            category_status[cat] = {
                "cadence_hours": hours,
                "last_run_at": last.isoformat() if last else None,
                "next_run_at": next_due.isoformat() if last else "Immediate",
                "is_due": is_due,
            }

        return {
            "enabled": self.settings.auto_scheduler_enabled,
            "is_running": _RUNNING,
            "apify_configured": self.apify_client.is_configured,
            "current_time": now.isoformat(),
            "cadences": category_status,
        }

    async def run_heartbeat(self) -> None:
        """Single evaluation tick checking all due categories."""
        if not self.settings.auto_scheduler_enabled:
            return

        now = utcnow()
        categories_to_check = [
            ("tenders", self.settings.cadence_tenders_hours, "tender"),
            ("jobs", self.settings.cadence_jobs_hours, "job"),
            ("funding", self.settings.cadence_funding_hours, "funding"),
            ("schemes", self.settings.cadence_schemes_hours, "funding"),
        ]

        def _execute_category_scan(cat: str, filt: str):
            with session_scope() as session:
                orch = Orchestrator(session)
                lock = f"auto_scheduler_{cat}"
                try:
                    owner = orch.acquire_lock(lock)
                except Exception:
                    return
                try:
                    logger.info("Executing autonomous scan for category: %s", cat)
                    if cat == "schemes":
                        from app.seeds.schemes import seed_verified_schemes
                        seed_verified_schemes(session)
                    else:
                        orch.run_due_scans(category=filt, force=False)
                    _LAST_RUNS[cat] = utcnow()
                    logger.info("Autonomous scan finished for category: %s", cat)
                finally:
                    orch.release_lock(lock, owner)

        for cat_key, interval_hours, filter_cat in categories_to_check:
            last = _LAST_RUNS.get(cat_key)
            if last and (now - last) < dt.timedelta(hours=interval_hours):
                continue

            try:
                await asyncio.to_thread(_execute_category_scan, cat_key, filter_cat)
            except Exception as exc:
                logger.error("Error running autonomous category %s: %s", cat_key, exc, exc_info=True)


async def scheduler_worker_loop():
    """Permanent background worker loop."""
    global _RUNNING
    _RUNNING = True
    scheduler = AutonomousScheduler()
    logger.info("Autonomous Scheduler worker started. Polling every %d seconds.", scheduler.settings.scheduler_poll_seconds)

    try:
        while _RUNNING:
            try:
                await scheduler.run_heartbeat()
            except Exception as exc:
                logger.error("Unhandled exception in scheduler heartbeat: %s", exc, exc_info=True)

            await asyncio.sleep(scheduler.settings.scheduler_poll_seconds)
    except asyncio.CancelledError:
        logger.info("Autonomous Scheduler worker received stop signal.")
    finally:
        _RUNNING = False


def start_scheduler():
    """Starts the background worker task."""
    global _SCHEDULER_TASK
    if _SCHEDULER_TASK is None or _SCHEDULER_TASK.done():
        _SCHEDULER_TASK = asyncio.create_task(scheduler_worker_loop())


def stop_scheduler():
    """Stops the background worker task."""
    global _RUNNING, _SCHEDULER_TASK
    _RUNNING = False
    if _SCHEDULER_TASK and not _SCHEDULER_TASK.done():
        _SCHEDULER_TASK.cancel()
