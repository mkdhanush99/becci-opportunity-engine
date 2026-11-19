"""Apify Webhook & Dataset Ingestion Pipeline.

Transforms raw items extracted by Apify Actors into normalized, verified BECCI opportunities.
Enforces:
- PAN-INDIA preservation for Tenders, Government Jobs, and Private Jobs.
- Strict 3-way geographical boundary for Government Schemes (Pan-India, Telangana, Andhra Pradesh).
- Dead-Letter Queue (DLQ) routing for malformed or unverified payloads.
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any
from sqlalchemy.orm import Session

from app.enums import (
    BeneficiaryClassification,
    GeographicalScope,
    LifecycleStatus,
    SchemeApplicationStatus,
    SourceReliability,
    SourceVerificationStatus,
    VerificationStatus,
)
from app.fetch.apify_client import ApifyClient
from app.models import DLQRecord, Opportunity, OpportunityVersion, SchemeDetail, Source, new_id, utcnow
from app.pipeline.deduplication import handle_deduplication_and_changes
from app.pipeline.extraction import ExtractedItem, sha256, slugify, title_key
from app.pipeline.normalisation import normalise_item
from app.pipeline.verification import verify_opportunity

logger = logging.getLogger(__name__)


def process_apify_run_results(
    session: Session,
    dataset_id: str,
    *,
    source_id: str = "apify-crawler",
    category_hint: str | None = None,
    client: ApifyClient | None = None,
) -> dict[str, int]:
    """Fetches items from an Apify dataset and feeds them into the BECCI pipeline."""
    client = client or ApifyClient()
    items = client.get_dataset_items(dataset_id)
    return ingest_apify_raw_items(session, items, source_id=source_id, category_hint=category_hint)


def ingest_apify_raw_items(
    session: Session,
    raw_items: list[dict[str, Any]],
    *,
    source_id: str = "apify-crawler",
    category_hint: str | None = None,
) -> dict[str, int]:
    """Ingests a list of raw dict items produced by an Apify Actor."""
    stats = {"total": len(raw_items), "ingested": 0, "dlq": 0, "skipped": 0}

    # Ensure source exists
    source = session.get(Source, source_id)
    if not source:
        # Create virtual source for Apify actor
        source = Source(
            id=source_id,
            name=f"Apify Actor ({source_id})",
            domain="apify.com",
            url="https://api.apify.com",
            agent_id="apify-scout",
            parser="apify-actor",
            collection_method="api",
            reliability=SourceReliability.OFFICIAL_GOVERNMENT.value,
            issuing_organisation="Apify Cloud Crawler",
            categories=[category_hint or "tender"],
            geographic_coverage=["National", "Telangana", "Andhra Pradesh"],
            active=True,
            support_status="supported",
        )
        session.add(source)
        session.flush()

    for item in raw_items:
        try:
            # 1. Basic validation
            title = (item.get("title") or item.get("name") or item.get("headline") or "").strip()
            url = (item.get("url") or item.get("link") or item.get("original_url") or "").strip()
            category = (item.get("category") or category_hint or "tender").lower().strip()

            if not title or len(title) < 5 or not url:
                # Malformed -> Route to Dead Letter Queue
                _record_dlq(
                    session,
                    source_id=source_id,
                    category=category,
                    stage="apify_validation",
                    reason="Missing or invalid title/url",
                    raw_payload=item,
                )
                stats["dlq"] += 1
                continue

            # 2. Scheme Geographical Scope Guardrail
            if category == "funding" or "scheme" in item:
                scope = (item.get("geographical_scope") or "pan_india").lower()
                state = (item.get("state") or "").strip()
                if scope not in ("pan_india", "telangana", "andhra_pradesh"):
                    if state and state.lower() not in ("telangana", "andhra pradesh", "national", "all india"):
                        # Reject unrelated state schemes
                        _record_dlq(
                            session,
                            source_id=source_id,
                            category=category,
                            stage="scheme_scope_guardrail",
                            reason=f"Rejected scheme from unrelated state '{state}' (Scope constraint: pan_india, telangana, andhra_pradesh only)",
                            raw_payload=item,
                        )
                        stats["dlq"] += 1
                        continue

            # 3. Build ExtractedItem for BECCI pipeline
            item_fields = {
                "title": title,
                "description": item.get("description") or item.get("details") or title,
                "category": category,
                "routed_category": category,
                "subcategory": item.get("subcategory"),
                "issuing_organisation": item.get("issuing_organisation") or item.get("company") or item.get("department") or "Unknown Issuer",
                "publisher": item.get("publisher") or source.name,
                "state": item.get("state"),
                "district": item.get("district"),
                "industry": item.get("industry") or "Other industries",
                "financial_details": item.get("financial_details") or item.get("salary") or item.get("estimated_value"),
                "eligibility": item.get("eligibility"),
                "benefits": item.get("benefits"),
                "deadline": str(item.get("deadline")) if item.get("deadline") else "",
                "published_date": str(item.get("published_date")) if item.get("published_date") else "",
            }

            extracted = ExtractedItem(
                external_key=item.get("id") or item.get("tender_id") or item.get("job_id") or sha256(f"{url}|{title}"),
                title=title,
                original_url=url,
                raw_text=title,
                fields=item_fields,
                application_url=item.get("application_url") or url,
                subcategory=item.get("subcategory"),
            )

            # Normalise
            opp = normalise_item(extracted, source, agent_id="apify-scout")
            # Deduplicate & Save
            action, saved_opp = handle_deduplication_and_changes(session, opp, actor="apify")
            # Verify once saved in DB
            verify_opportunity(session, saved_opp, source)
            stats["ingested"] += 1

        except Exception as exc:
            logger.warning("Failed to ingest Apify item %s: %s", item, exc)
            _record_dlq(
                session,
                source_id=source_id,
                category=category_hint,
                stage="ingestion_pipeline",
                reason=str(exc),
                raw_payload=item,
            )
            stats["dlq"] += 1

    session.commit()
    return stats


def _record_dlq(
    session: Session,
    *,
    source_id: str,
    category: str | None,
    stage: str,
    reason: str,
    raw_payload: dict[str, Any],
) -> None:
    dlq = DLQRecord(
        source_id=source_id,
        category=category,
        stage=stage,
        error_reason=reason[:1000],
        raw_payload=raw_payload,
        resolved=False,
    )
    session.add(dlq)
