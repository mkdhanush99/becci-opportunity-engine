"""Deduplication and Change Detection Engine.

Intelligently detects duplicate opportunities and identifies changes over time.
"""
from __future__ import annotations

import datetime as dt
from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.enums import LifecycleStatus, SourceReliability
from app.models import Opportunity, OpportunitySourceLink, OpportunityVersion, utcnow
from app.pipeline.extraction import title_key


RELIABILITY_RANK = {
    SourceReliability.OFFICIAL_GOVERNMENT: 4,
    SourceReliability.OFFICIAL_EMPLOYER: 3,
    SourceReliability.RECOGNISED_INSTITUTION: 2,
    SourceReliability.THIRD_PARTY: 1,
}


def find_existing_match(session: Session, opp: Opportunity) -> Opportunity | None:
    """Finds an existing opportunity that matches by external_key, reference_number, or title similarity."""
    # 1. Exact source + key match
    stmt = select(Opportunity).where(
        Opportunity.source_id == opp.source_id,
        Opportunity.external_key == opp.external_key
    )
    existing = session.scalars(stmt).first()
    if existing:
        return existing

    # 2. Reference number match within the same issuing organisation / category
    if opp.reference_number:
        stmt = select(Opportunity).where(
            Opportunity.category == opp.category,
            Opportunity.reference_number == opp.reference_number
        )
        existing = session.scalars(stmt).first()
        if existing:
            return existing

    # 3. Fuzzy title match with exact organisation/category
    stmt = select(Opportunity).where(
        Opportunity.category == opp.category,
        Opportunity.lifecycle_status.notin_([LifecycleStatus.REJECTED, LifecycleStatus.WITHDRAWN])
    )
    candidates = session.scalars(stmt).all()
    t_clean = title_key(opp.title)

    for cand in candidates:
        cand_clean = title_key(cand.title)
        ratio = fuzz.token_set_ratio(t_clean, cand_clean)
        if ratio >= 90:
            # High confidence duplicate
            return cand

    return None


def handle_deduplication_and_changes(
    session: Session, new_opp: Opportunity, actor: str = "orchestrator"
) -> tuple[str, Opportunity]:
    """Processes an incoming opportunity against the existing database.

    Returns:
        (action, saved_opportunity) where action is 'inserted', 'updated', or 'merged_duplicate'
    """
    now = utcnow()
    existing = find_existing_match(session, new_opp)

    if not existing:
        # Brand new opportunity
        session.add(new_opp)
        return "inserted", new_opp

    # Case A: Same source and external key -> Change Detection
    if existing.source_id == new_opp.source_id and existing.external_key == new_opp.external_key:
        changed_fields = []
        significant = False

        existing.last_seen_in_source_at = now
        existing.last_checked_at = now

        # Check title changes
        if existing.raw_title != new_opp.raw_title:
            changed_fields.append("title")
            existing.raw_title = new_opp.raw_title
            # Keep presentation title updated if admin hasn't diverged
            existing.title = new_opp.title

        # Check deadline changes (critical)
        if existing.deadline != new_opp.deadline:
            changed_fields.append("deadline")
            existing.deadline = new_opp.deadline
            existing.expiry_status = new_opp.expiry_status
            significant = True

        # Check reference number changes
        if existing.reference_number != new_opp.reference_number and new_opp.reference_number:
            changed_fields.append("reference_number")
            existing.reference_number = new_opp.reference_number
            significant = True

        # Check content fingerprint
        if existing.content_fingerprint != new_opp.content_fingerprint:
            changed_fields.append("raw_text")
            existing.content_fingerprint = new_opp.content_fingerprint
            existing.raw_text = new_opp.raw_text

        if changed_fields:
            existing.last_updated_at = now
            if existing.lifecycle_status == LifecycleStatus.PUBLISHED:
                existing.lifecycle_status = LifecycleStatus.UPDATED

            new_version_num = len(existing.versions) + 1
            ver = OpportunityVersion(
                opportunity_id=existing.id,
                version=new_version_num,
                snapshot={
                    "title": existing.title,
                    "deadline": existing.deadline.isoformat() if existing.deadline else None,
                    "reference_number": existing.reference_number,
                    "lifecycle_status": existing.lifecycle_status,
                },
                changed_fields=changed_fields,
                significant=significant,
                reason="source_change",
                actor=actor,
                created_at=now,
            )
            session.add(ver)
            return "updated", existing

        return "unchanged", existing

    # Case B: Duplicate across different sources / listings
    # Decide which record is primary based on source reliability
    existing_rank = RELIABILITY_RANK.get(existing.source_type, 0)
    new_rank = RELIABILITY_RANK.get(new_opp.source_type, 0)

    # Attach supporting source link
    link = OpportunitySourceLink(
        opportunity_id=existing.id,
        source_id=new_opp.source_id,
        url=new_opp.original_url,
        role="supporting",
        reliability=new_opp.source_type,
        added_at=now,
    )
    session.add(link)
    existing.last_checked_at = now

    # If the incoming source is strictly more reliable (e.g. Official Govt vs Third Party), note it
    if new_rank > existing_rank:
        existing.merge_reason = f"Supporting source {new_opp.source_name} has higher reliability than current primary"

    return "merged_duplicate", existing
