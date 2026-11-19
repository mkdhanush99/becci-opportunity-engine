"""Normalisation Engine: converts raw ExtractedItems into validated Opportunity instances.

Preserves raw extracted content separately from normalised presentation fields.
Derives fingerprints, slugs, and geographic classifications.
"""
from __future__ import annotations

import datetime as dt
from app.enums import ExpiryStatus, LifecycleStatus, SourceReliability
from app.models import Evidence, Opportunity, OpportunityVersion, Source, new_id, utcnow
from app.pipeline.extraction import ExtractedItem, parse_date, sha256, slugify, title_key


def normalise_item(item: ExtractedItem, source: Source, agent_id: str, is_fixture: bool = False) -> Opportunity:
    now = utcnow()
    today = now.date()

    # Dates
    pub_date = parse_date(item.fields.get("published_date", ""))
    open_date = parse_date(item.fields.get("opening_date", ""))
    deadline = parse_date(item.fields.get("deadline", ""))
    event_date = parse_date(item.fields.get("event_date", ""))

    # Expiry evaluation
    if deadline:
        if deadline < today:
            exp_status = ExpiryStatus.EXPIRED
        elif (deadline - today).days <= 7:
            exp_status = ExpiryStatus.CLOSING_SOON
        else:
            exp_status = ExpiryStatus.ACTIVE
    else:
        exp_status = ExpiryStatus.DATE_UNAVAILABLE

    # Geography
    state = source.geographic_coverage[0] if len(source.geographic_coverage) == 1 and source.geographic_coverage[0] != "National" else None
    if not state and "telangana" in item.title.lower() or "tgpsc" in item.external_key:
        state = "Telangana"
    elif not state and "maharashtra" in item.title.lower() or "mpsc" in item.external_key:
        state = "Maharashtra"

    location_type = "national" if not state else "state"

    # Fingerprints for deduplication & change detection
    content_fp = sha256(item.raw_text[:20000])
    title_fp = sha256(title_key(item.title))

    opp_id = new_id()
    slug = f"{slugify(item.title)}-{opp_id[:8]}"

    opp = Opportunity(
        id=opp_id,
        external_key=item.external_key,
        slug=slug,
        # Presentation fields
        title=item.title,
        description=item.fields.get("description") or (item.raw_text[:400] + "..." if len(item.raw_text) > 400 else item.raw_text),
        category=source.categories[0] if source.categories else "job",
        subcategory=item.subcategory,
        # Organisation
        issuing_organisation=item.fields.get("issuing_organisation") or source.issuing_organisation or source.name,
        publisher=source.name,
        source_type=source.reliability,
        source_name=source.name,
        # Location
        country="India",
        state=state,
        city=item.fields.get("city"),
        location_type=location_type,
        # Details
        industry=item.fields.get("industry") or (source.industry_relevance[0] if source.industry_relevance else None),
        qualification=item.fields.get("qualification"),
        experience=item.fields.get("experience"),
        eligibility=item.fields.get("eligibility"),
        benefits=item.fields.get("benefits"),
        financial_details=item.fields.get("financial_details"),
        application_method=item.fields.get("application_method"),
        reference_number=item.fields.get("reference_number"),
        positions=item.fields.get("positions"),
        # Dates
        published_date=pub_date,
        opening_date=open_date,
        deadline=deadline,
        event_date=event_date,
        first_discovered_at=now,
        last_checked_at=now,
        last_updated_at=now,
        last_seen_in_source_at=now,
        # References
        original_url=item.original_url,
        application_url=item.application_url,
        supporting_documents=item.documents,
        # Status
        lifecycle_status=LifecycleStatus.DISCOVERED,
        verification_status="pending",
        expiry_status=exp_status,
        featured=False,
        # System
        agent_id=agent_id,
        source_id=source.id,
        confidence="medium" if source.reliability == SourceReliability.OFFICIAL_GOVERNMENT else "low",
        confidence_reasons=["Discovered from registered source: " + source.name],
        content_fingerprint=content_fp,
        title_fingerprint=title_fp,
        extracted_at=now,
        is_fixture=is_fixture,
        # Raw immutable values
        raw_title=item.title,
        raw_text=item.raw_text,
        raw_fields=item.fields,
    )

    # Attach evidence records
    for c in item.claims:
        opp.evidence.append(
            Evidence(
                opportunity_id=opp_id,
                field=c.field,
                value=c.value,
                snippet=c.snippet,
                source_url=item.original_url,
                found_in_source=True,
                captured_at=now,
            )
        )

    # Attach initial version
    opp.versions.append(
        OpportunityVersion(
            opportunity_id=opp_id,
            version=1,
            snapshot={
                "title": opp.title,
                "deadline": opp.deadline.isoformat() if opp.deadline else None,
                "reference_number": opp.reference_number,
                "lifecycle_status": opp.lifecycle_status,
            },
            changed_fields=["initial_creation"],
            significant=True,
            reason="extracted",
            actor="pipeline",
            created_at=now,
        )
    )

    return opp
