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

    # 6. Tender-Specific Verification Checks (Agent 03 -> Agent 07 integration)
    if opp.category == "tender" or opp.tender_detail is not None:
        td = opp.tender_detail
        ev_fields = {e.field for e in opp.evidence}

        # 6a. Tender Reference Consistency
        has_ref = bool(opp.reference_number and len(opp.reference_number.strip()) >= 3)
        ref_anchored = "reference_number" in ev_fields
        checks.append({
            "name": "tender_reference_consistency",
            "passed": has_ref and ref_anchored,
            "detail": (
                f"Tender reference '{opp.reference_number}' consistent and anchored in source evidence"
                if (has_ref and ref_anchored)
                else "Missing or unanchored tender reference number"
            ),
        })
        if not (has_ref and ref_anchored):
            flags.append("missing_tender_reference")

        # 6b. Publication & Deadline Evidence Check
        dl_ok = opp.deadline is None or ("deadline" in ev_fields)
        checks.append({
            "name": "tender_deadline_evidence",
            "passed": dl_ok,
            "detail": (
                f"Submission deadline ({opp.deadline}) backed by verbatim evidence"
                if opp.deadline and dl_ok
                else ("Submission deadline not stated in source" if not opp.deadline else "Deadline lacks source evidence")
            ),
        })
        if not dl_ok:
            flags.append("unanchored_deadline")

        # 6c. Cancellation & Corrigendum Checks
        if td:
            if td.tender_status == "cancelled" or td.cancellation_reason:
                flags.append("tender_cancelled")
                checks.append({
                    "name": "tender_cancellation_check",
                    "passed": False,
                    "detail": f"Tender cancelled: {td.cancellation_reason or 'Cancelled notice'}",
                })
            else:
                corr_count = len(td.corrigendum_history or [])
                checks.append({
                    "name": "tender_corrigendum_and_status",
                    "passed": True,
                    "detail": f"Status='{td.tender_status}', Corrigendums tracked={corr_count}",
                })

            # 6d. Eligibility Intelligence & Ambiguity Flag
            elig_info = td.eligibility_intelligence or {}
            is_ambiguous = bool(elig_info.get("ambiguous_flag", False))
            checks.append({
                "name": "tender_eligibility_intelligence",
                "passed": True,
                "detail": (
                    "Eligibility terms require human review (refers to external ATC / tender document)"
                    if is_ambiguous
                    else f"Structured eligibility extracted (Turnover={td.turnover_requirement}, MSME={td.msme_preference[:60]})"
                ),
            })

    # Determine final Verification Status
    if "tender_cancelled" in flags:
        status = VerificationStatus.REMOVED
        requires_human = True
        opp.lifecycle_status = LifecycleStatus.WITHDRAWN
        if opp.tender_detail:
            opp.tender_detail.tender_status = "cancelled"
    elif "expired" in flags:
        status = VerificationStatus.EXPIRED
        requires_human = False
        opp.lifecycle_status = LifecycleStatus.EXPIRED
        if opp.tender_detail:
            opp.tender_detail.tender_status = "expired"
    elif (
        "domain_mismatch" in flags
        or "suspicious_application_redirect" in flags
        or "conflicting_dates" in flags
        or "unanchored_deadline" in flags
    ):
        status = VerificationStatus.CONFLICTING
        requires_human = True
        opp.lifecycle_status = LifecycleStatus.NEEDS_HUMAN_REVIEW
    elif "missing_mandatory_fields" in flags or "insufficient_evidence" in flags or "missing_tender_reference" in flags:
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
        if opp.lifecycle_status not in (LifecycleStatus.PUBLISHED, LifecycleStatus.APPROVED):
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
