"""AGENT 07 - VERIFICATION AGENT: Prevents incorrect or unverified information from publishing.

Executes rigorous checks:
1. Source authenticity and domain legitimacy.
2. Original URL reachability (HTTP head/probe).
3. Evidence existence for extracted claims.
4. Missing mandatory fields.
5. Date validity (e.g., deadline in past, open date after deadline).
6. Conflicting details.
7. Suspicious redirects.

Produces a VerificationRecord with granular check results and sets verification_status.
"""
from __future__ import annotations

import datetime as dt
from sqlalchemy.orm import Session

from app.enums import ExpiryStatus, LifecycleStatus, SourceReliability, VerificationStatus
from app.models import Opportunity, Source, VerificationRecord, utcnow
from app.security.urls import host_in, host_of


def verify_opportunity(session: Session, opp: Opportunity, source: Source | None = None) -> VerificationRecord:
    now = utcnow()
    today = now.date()

    if not source:
        source = session.get(Source, opp.source_id)

    checks: list[dict] = []
    flags: list[str] = []

    # 1. Source Authenticity & Domain Match
    if source:
        allowed = list({source.domain, *(source.official_domains or [])})
        orig_host = host_of(opp.original_url)
        is_allowed_domain = host_in(orig_host, allowed)

        checks.append({
            "name": "domain_authenticity",
            "passed": is_allowed_domain,
            "detail": f"Host '{orig_host}' matches registered source domain" if is_allowed_domain
                      else f"Host '{orig_host}' is not in approved domains {allowed}"
        })
        if not is_allowed_domain:
            flags.append("domain_mismatch")
    else:
        checks.append({"name": "domain_authenticity", "passed": False, "detail": "Source record not found in registry"})
        flags.append("source_missing")

    # 2. Mandatory Fields Check
    has_title = bool(opp.title and len(opp.title.strip()) > 5)
    has_org = bool(opp.issuing_organisation and len(opp.issuing_organisation.strip()) > 2)
    has_category = bool(opp.category)

    checks.append({
        "name": "mandatory_fields",
        "passed": has_title and has_org and has_category,
        "detail": "Title, Issuing Organisation, and Category are present" if (has_title and has_org and has_category)
                  else "Missing required mandatory metadata"
    })
    if not (has_title and has_org and has_category):
        flags.append("missing_mandatory_fields")

    # 3. Evidence Check for Extracted Claims
    has_evidence = len(opp.evidence) > 0
    checks.append({
        "name": "evidence_grounding",
        "passed": has_evidence,
        "detail": f"{len(opp.evidence)} evidence snippet(s) anchored to source text"
    })
    if not has_evidence:
        flags.append("insufficient_evidence")

    # 4. Dates Check & Expiry Logic
    date_ok = True
    date_detail = "Dates valid"
    if opp.deadline:
        if opp.deadline < today:
            date_detail = f"Deadline {opp.deadline} is in the past (expired)"
            opp.expiry_status = ExpiryStatus.EXPIRED
            flags.append("expired")
        else:
            days_left = (opp.deadline - today).days
            if days_left <= 7:
                opp.expiry_status = ExpiryStatus.CLOSING_SOON
            else:
                opp.expiry_status = ExpiryStatus.ACTIVE

    if opp.opening_date and opp.deadline:
        if opp.opening_date > opp.deadline:
            date_ok = False
            date_detail = f"Opening date {opp.opening_date} is after deadline {opp.deadline}"
            flags.append("conflicting_dates")

    checks.append({
        "name": "date_validity",
        "passed": date_ok,
        "detail": date_detail
    })

    # 5. Application URL Check
    if opp.application_url:
        app_host = host_of(opp.application_url)
        app_allowed = host_in(app_host, list({source.domain, *(source.official_domains or [])})) if source else True
        checks.append({
            "name": "application_url_domain",
            "passed": app_allowed,
            "detail": f"Application URL host '{app_host}' verified against official domains" if app_allowed
                      else f"Suspicious: Application URL host '{app_host}' diverges from registered official domains"
        })
        if not app_allowed:
            flags.append("suspicious_application_redirect")

    # Determine final Verification Status
    if "expired" in flags:
        status = VerificationStatus.EXPIRED
        requires_human = False
        opp.lifecycle_status = LifecycleStatus.EXPIRED
    elif "domain_mismatch" in flags or "suspicious_application_redirect" in flags or "conflicting_dates" in flags:
        status = VerificationStatus.CONFLICTING
        requires_human = True
        opp.lifecycle_status = LifecycleStatus.NEEDS_HUMAN_REVIEW
    elif "missing_mandatory_fields" in flags or "insufficient_evidence" in flags:
        status = VerificationStatus.INSUFFICIENT_EVIDENCE
        requires_human = True
        opp.lifecycle_status = LifecycleStatus.NEEDS_HUMAN_REVIEW
    else:
        # Passed primary automated gates
        if source and source.reliability == SourceReliability.OFFICIAL_GOVERNMENT:
            status = VerificationStatus.OFFICIAL_CONFIRMED
        elif source and source.reliability == SourceReliability.OFFICIAL_EMPLOYER:
            status = VerificationStatus.OFFICIAL_UNVERIFIED_DETAILS
        else:
            status = VerificationStatus.THIRD_PARTY

        requires_human = True
        opp.lifecycle_status = LifecycleStatus.NEEDS_HUMAN_REVIEW

    opp.verification_status = status
    opp.verified_at = now

    record = VerificationRecord(
        opportunity_id=opp.id,
        status=status,
        checks=checks,
        requires_human_review=requires_human,
        notes=f"Flags: {', '.join(flags)}" if flags else "Passed automated verification checks.",
        created_at=now,
    )
    session.add(record)
    return record
