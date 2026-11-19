"""Normalisation Engine: converts raw ExtractedItems into validated Opportunity instances.

Preserves raw extracted content separately from normalised presentation fields.
Derives fingerprints, slugs, and geographic classifications.
"""
from __future__ import annotations

import datetime as dt
from app.enums import ExpiryStatus, LifecycleStatus, SourceReliability
from app.models import Evidence, Opportunity, OpportunityVersion, SchemeDetail, Source, TenderDetail, new_id, utcnow
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
    state = item.fields.get("state")
    if not state:
        state = source.geographic_coverage[0] if len(source.geographic_coverage) == 1 and source.geographic_coverage[0] != "National" else None
    if not state and ("telangana" in item.title.lower() or "tgpsc" in item.external_key):
        state = "Telangana"
    elif not state and ("andhra" in item.title.lower() or "appsc" in item.external_key or "apiic" in item.external_key):
        state = "Andhra Pradesh"
    elif not state and ("maharashtra" in item.title.lower() or "mpsc" in item.external_key):
        state = "Maharashtra"

    location_type = item.fields.get("location_type") or ("national" if not state else "state")


    # Fingerprints for deduplication & change detection
    content_fp = sha256(item.raw_text[:20000])
    title_fp = sha256(title_key(item.title))

    opp_id = new_id()
    slug = f"{slugify(item.title)}-{opp_id[:8]}"

    routed_cat = item.fields.get("routed_category") or item.fields.get("category")
    category = routed_cat or (source.categories[0] if source.categories else "job")

    opp = Opportunity(
        id=opp_id,
        external_key=item.external_key,
        slug=slug,
        # Presentation fields
        title=item.title,
        description=item.fields.get("description") or (item.raw_text[:400] + "..." if len(item.raw_text) > 400 else item.raw_text),
        category=category,
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

    # Attach 1-to-1 TenderDetail record for procurement tenders
    if opp.category == "tender":
        f = item.fields
        opp.tender_detail = TenderDetail(
            opportunity_id=opp_id,
            tender_id=f.get("tender_id") or opp.reference_number,
            reference_number=opp.reference_number,
            issuing_authority=opp.issuing_organisation,
            department=f.get("department") or "Not stated",
            tender_category=f.get("tender_category") or (opp.subcategory or "Not stated"),
            product_category=f.get("product_category") or "Not stated",
            sector=f.get("sector") or opp.industry or "Other industries",
            estimated_value=f.get("estimated_value") or "Not published",
            emd_amount=f.get("emd_amount") or "Not published",
            tender_fee=f.get("tender_fee") or "Not published",
            document_download_date=parse_date(f.get("document_download_date", "")),
            pre_bid_date=parse_date(f.get("pre_bid_date", "")),
            pre_bid_details=f.get("pre_bid_details") or "Not published",
            bid_opening_date=parse_date(f.get("bid_opening_date", "")) or open_date,
            turnover_requirement=f.get("turnover_requirement") or "Not stated",
            experience_requirement=f.get("experience_requirement") or "Not stated",
            required_registrations=f.get("required_registrations") or [],
            msme_preference=f.get("msme_preference") or "Not stated",
            eligibility_intelligence=f.get("eligibility_intelligence") or {},
            tender_status=f.get("tender_status") or "open",
            corrigendum_history=f.get("corrigendum_history") or [],
            cancellation_reason=f.get("cancellation_reason"),
            updated_at=now,
        )

    # Attach 1-to-1 SchemeDetail record for government schemes
    if opp.category == "funding" or "scheme_detail" in item.fields:
        s_data = item.fields.get("scheme_detail") or {}
        scope = s_data.get("geographical_scope")
        if not scope:
            if opp.state == "Telangana":
                scope = "telangana"
            elif opp.state == "Andhra Pradesh":
                scope = "andhra_pradesh"
            else:
                scope = "pan_india"

        opp.scheme_detail = SchemeDetail(
            opportunity_id=opp_id,
            scheme_name=s_data.get("scheme_name") or opp.title,
            government_department=s_data.get("government_department") or opp.issuing_organisation,
            geographical_scope=scope,
            beneficiary_classification=s_data.get("beneficiary_classification") or (
                "obc_bc_specific" if "backward classes" in (opp.issuing_organisation or "").lower() or "bc" in opp.title.lower() else "general_msme"
            ),
            beneficiary_categories=s_data.get("beneficiary_categories") or ["entrepreneurs"],
            applicable_castes=s_data.get("applicable_castes") or (["OBC"] if "nbcfdc" in (opp.issuing_organisation or "").lower() else ["All"]),
            domicile_required=s_data.get("domicile_required", bool(opp.state in ("Telangana", "Andhra Pradesh"))),
            domicile_state=s_data.get("domicile_state") or opp.state,
            income_limit=s_data.get("income_limit"),
            age_limit=s_data.get("age_limit"),
            education_requirement=s_data.get("education_requirement") or opp.qualification,
            occupation_requirement=s_data.get("occupation_requirement"),
            business_eligibility=s_data.get("business_eligibility") or opp.eligibility,
            benefit_type=s_data.get("benefit_type") or "loan",
            benefit_amount=s_data.get("benefit_amount") or opp.financial_details,
            source_verification_status=s_data.get("source_verification_status") or "verified",
            application_status=s_data.get("application_status") or "continuous",
            required_documents=s_data.get("required_documents") or [],
            official_application_url=s_data.get("official_application_url") or opp.application_url or opp.original_url,
            official_guideline_url=s_data.get("official_guideline_url") or opp.original_url,
            last_verified_at=now,
            updated_at=now,
        )

    return opp


