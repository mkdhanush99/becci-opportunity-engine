"""Webhook endpoints for external crawler integrations (Apify)."""
from __future__ import annotations

import logging
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.pipeline.apify_ingestion import process_apify_run_results

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/webhooks", tags=["Webhooks"])


@router.post("/apify")
async def handle_apify_webhook(
    request: Request,
    secret: str | None = Query(None),
    db: Session = Depends(get_db),
):
    """Webhook listener for Apify Actor completion events.
    
    Processes the defaultDatasetId produced by the actor, extracts opportunities,
    enforces validation and geographic boundaries, and updates BECCI repository.
    """
    settings = get_settings()
    if settings.apify_webhook_secret and secret and secret != settings.apify_webhook_secret:
        raise HTTPException(status_code=403, detail="Invalid webhook secret")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event_type = payload.get("eventType") or payload.get("type") or "ACTOR.RUN.SUCCEEDED"
    event_data = payload.get("eventData") or payload.get("resource") or {}

    dataset_id = (
        event_data.get("defaultDatasetId")
        or payload.get("defaultDatasetId")
        or event_data.get("datasetId")
    )
    actor_id = event_data.get("actId") or event_data.get("actorId") or payload.get("actorId") or "apify-crawler"
    category = payload.get("category") or "tender"

    if not dataset_id:
        logger.warning("Received Apify webhook without datasetId: %s", payload)
        return {"status": "ignored", "reason": "No defaultDatasetId in payload"}

    logger.info("Processing Apify webhook for actor %s, dataset %s (eventType: %s)", actor_id, dataset_id, event_type)
    stats = process_apify_run_results(
        db,
        dataset_id,
        source_id=f"apify-{actor_id}",
        category_hint=category,
    )

    return {
        "status": "success",
        "dataset_id": dataset_id,
        "actor_id": actor_id,
        "stats": stats,
    }
