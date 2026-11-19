"""BECCI Opportunity Matching, Eligibility Intelligence & Configurable Ranking Engine.

Evaluates a BusinessProfile against verified, published opportunities (tenders, funding schemes,
vendor empanelments, innovation challenges, and relevant recruitment opportunities) with:
- Transparent multi-factor relevance scoring (configurable via MatchingConfig)
- Structured eligibility intelligence using the 5 controlled statuses
- Strict safety gates: unverified or expired opportunities NEVER appear as high-priority active recommendations
- Informational disclaimer: NEVER claims guaranteed eligibility
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.enums import (
    EligibilityMatchStatus,
    ExpiryStatus,
    PUBLIC_STATUSES,
    TenderStatus,
    VerificationStatus,
)
from app.models import BusinessProfile, MatchingConfig, Opportunity, utcnow

ELIGIBILITY_DISCLAIMER = (
    "Assessment is informational based on published source text; final eligibility is determined "
    "solely by the issuing authority."
)

_AMOUNT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(lakh|lakhs|crore|crores)\b", re.I)
_YEARS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:year|years|yr|yrs)\b", re.I)
_NOT_STATED_VALS = {"", "not stated", "not published", "na", "n/a", "none"}


@dataclass
class MatchEvaluation:
    opportunity: Opportunity
    relevance_score: float
    is_active_recommendation: bool
    eligibility_status: str
    why_it_matches: list[str] = field(default_factory=list)
    satisfied_conditions: list[str] = field(default_factory=list)
    missing_requirements: list[str] = field(default_factory=list)
    details_to_confirm: list[str] = field(default_factory=list)
    required_documents: list[str] = field(default_factory=list)
    score_breakdown: dict[str, dict] = field(default_factory=dict)
    ranking_reasons: list[str] = field(default_factory=list)
    disclaimer: str = ELIGIBILITY_DISCLAIMER


def get_or_create_matching_config(session: Session) -> MatchingConfig:
    cfg = session.get(MatchingConfig, "default")
    if not cfg:
        cfg = MatchingConfig(id="default", updated_by="system", updated_at=utcnow())
        session.add(cfg)
        session.commit()
        session.refresh(cfg)
    return cfg


def _parse_lakhs(text: str) -> float | None:
    if not text:
        return None
    m = _AMOUNT_RE.search(text)
    if not m:
        return None
    val = float(m.group(1).replace(",", ""))
    unit = m.group(2).lower()
    return val * 100.0 if unit.startswith("crore") else val


def _parse_years(text: str) -> float | None:
    if not text:
        return None
    m = _YEARS_RE.search(text)
    if not m:
        return None
    return float(m.group(1))


def _tokenise(items: list[str] | str | None) -> set[str]:
    if not items:
        return set()
    raw = " ".join(items) if isinstance(items, list) else str(items)
    tokens = {w.lower() for w in re.findall(r"[a-zA-Z0-9]{3,}", raw)}
    stop = {
        "and", "for", "the", "with", "from", "into", "under", "services", "service",
        "goods", "supply", "work", "works", "india", "indian", "limited", "private",
        "govt", "government", "ministry", "department", "office", "agency", "other",
        "general", "national", "state", "district", "bid", "tender", "rfp", "proposal",
    }
    return tokens - stop


def _is_expired_or_closed(opp: Opportunity, today: dt.date) -> bool:
    if opp.deadline and opp.deadline < today:
        return True
    if opp.expiry_status == ExpiryStatus.EXPIRED:
        return True
    td = opp.tender_detail
    if td and td.tender_status in (TenderStatus.EXPIRED, TenderStatus.CANCELLED, TenderStatus.CLOSED):
        return True
    return False


def is_incomplete_eligibility(opp: Opportunity) -> tuple[bool, list[str]]:
    """Checks whether an opportunity has incomplete or ambiguous eligibility metadata for admin review."""
    reasons: list[str] = []
    td = opp.tender_detail
    if td:
        ei = td.eligibility_intelligence or {}
        if ei.get("ambiguous_flag"):
            reasons.append("Eligibility flagged ambiguous (e.g., 'As per ATC' or missing turnover/experience)")
        if (td.turnover_requirement or "").strip().lower() in _NOT_STATED_VALS:
            reasons.append("Turnover requirement not stated in extracted source")
        if (td.experience_requirement or "").strip().lower() in _NOT_STATED_VALS:
            reasons.append("Experience requirement not stated in extracted source")
        if td.tender_status == TenderStatus.UNDER_VERIFICATION:
            reasons.append("Tender status is under_verification (manual review required)")
    else:
        elig = (opp.eligibility or "").strip().lower()
        if not elig or elig in _NOT_STATED_VALS or "refer to official" in elig:
            reasons.append("Eligibility text refers to external document without structured criteria")
    if opp.deadline is None:
        reasons.append("Submission deadline not published")
    return (len(reasons) > 0), reasons


def _score_sector_and_capabilities(
    profile: BusinessProfile, opp: Opportunity
) -> tuple[float, list[str], list[str]]:
    """Returns (0.0..1.0 score, why_matches, ranking_reasons)."""
    td = opp.tender_detail
    opp_sector = (td.sector if td and td.sector else opp.industry) or ""
    p_sector = (profile.becci_sector or "").strip()
    sec_sectors = [s.strip().lower() for s in (profile.secondary_sectors or []) if s]

    why: list[str] = []
    reasons: list[str] = []

    profile_tokens = _tokenise(
        (profile.capabilities or [])
        + (profile.products_and_services or [])
        + ([profile.industry] if profile.industry else [])
    )
    opp_text_parts = [opp.title or "", opp.description or ""]
    if td:
        opp_text_parts.append(td.product_category or "")
    opp_tokens = _tokenise(opp_text_parts)
    overlap = sorted(profile_tokens & opp_tokens)

    if opp_sector and p_sector and opp_sector.lower() == p_sector.lower():
        score = 1.0
        why.append(f"Primary BECCI sector matches ({p_sector})")
        reasons.append(f"Exact sector match: {p_sector}")
        if overlap:
            why.append(f"Capability/product keyword alignment: {', '.join(overlap[:5])}")
        return score, why, reasons

    if opp_sector and opp_sector.lower() in sec_sectors:
        score = 0.80 if overlap else 0.75
        why.append(f"Secondary BECCI sector matches ({opp_sector})")
        reasons.append(f"Secondary sector match: {opp_sector}")
        if overlap:
            why.append(f"Capability/product keyword alignment: {', '.join(overlap[:5])}")
        return score, why, reasons

    if overlap:
        score = min(0.85, 0.45 + 0.15 * len(overlap))
        why.append(f"Business capabilities/products match opportunity scope ({', '.join(overlap[:5])})")
        reasons.append(f"Capability match on {len(overlap)} keyword(s)")
        return score, why, reasons

    # Funding & innovation challenges often span multiple sectors when general MSME/SC-ST support
    if opp.category == "funding" and opp_sector.lower() in ("", "services", "other industries", "finance and professional services"):
        why.append("Cross-sector MSME / enterprise funding programme applicable across sectors")
        reasons.append("Cross-sector funding relevance")
        return 0.65, why, reasons

    return 0.0, why, reasons


def _score_geography(profile: BusinessProfile, opp: Opportunity) -> tuple[float, list[str], list[str], list[str]]:
    """Returns (0.0..1.0 score, why_matches, missing_or_notes, ranking_reasons)."""
    p_state = (profile.state or "").strip()
    p_dist = (profile.district or "").strip()
    o_state = (opp.state or "").strip()
    o_city = (opp.city or "").strip()

    why: list[str] = []
    notes: list[str] = []
    reasons: list[str] = []

    if not o_state or opp.location_type == "national":
        why.append("National / All-India geographic coverage")
        reasons.append("Open nationwide")
        return 0.80, why, notes, reasons

    if p_state and o_state.lower() == p_state.lower():
        if p_dist and o_city and (p_dist.lower() in o_city.lower() or o_city.lower() in p_dist.lower()):
            why.append(f"Direct state and district/city match ({o_city}, {o_state})")
            reasons.append(f"Local match: {o_city}, {o_state}")
            return 1.0, why, notes, reasons
        why.append(f"Operating state matches ({o_state})")
        reasons.append(f"State match: {o_state}")
        return 0.90, why, notes, reasons

    notes.append(f"Opportunity is located in {o_state} (business is based in {p_state or 'another state'})")
    return 0.15, why, notes, reasons


def _evaluate_eligibility(
    profile: BusinessProfile,
    opp: Opportunity,
    *,
    is_expired: bool,
    sector_score: float,
) -> tuple[str, float, list[str], list[str], list[str], list[str]]:
    """Returns (eligibility_status, eligibility_score, satisfied, missing, confirm, required_docs)."""
    satisfied: list[str] = []
    missing: list[str] = []
    confirm: list[str] = []
    req_docs: list[str] = []

    td = opp.tender_detail
    ei = (td.eligibility_intelligence or {}) if td else {}
    raw_text_low = (opp.raw_text or "").lower()
    elig_text_low = (opp.eligibility or "").lower()

    # Collect official required documents from structured extraction
    if td and td.required_registrations:
        for r in td.required_registrations:
            if r not in req_docs:
                req_docs.append(r)
    if opp.category == "funding":
        req_docs.extend(["Identity / Business Registration Proof", "Official Scheme Application Form"])
        if "udyam" in raw_text_low or "msme" in raw_text_low:
            if "Udyam Registration Certificate" not in req_docs:
                req_docs.append("Udyam Registration Certificate")

    # Hard gate 1: Expired / Cancelled
    if is_expired:
        missing.append("Opportunity deadline has passed or notice has been cancelled/closed")
        return EligibilityMatchStatus.NOT_ELIGIBLE.value, 0.0, satisfied, missing, confirm, req_docs

    # Hard gate 2: Unverified source status
    unverified = opp.verification_status != VerificationStatus.OFFICIAL_CONFIRMED
    if unverified:
        confirm.append(f"Source verification status is '{opp.verification_status}'; manual verification required")

    hard_disqualifier = False
    profile_licences_low = {x.strip().lower() for x in (profile.licences_and_registrations or []) if x}

    # --- 1. MSME / Udyam & MSE Relaxation check ---
    msme_text = (td.msme_preference if td else "") or ""
    mse_relaxation = "mse relaxation" in msme_text.lower() and "yes" in msme_text.lower()
    mse_pref = "mse" in msme_text.lower() or "udyam" in msme_text.lower()
    if mse_pref:
        if profile.msme_udyam_status == "registered":
            satisfied.append("MSME/Udyam registration aligns with MSE preference / exemption benefits")
            if mse_relaxation:
                satisfied.append("Eligible for MSE relaxation on experience/turnover as noted in source")
        elif profile.msme_udyam_status in ("not_registered", "applied", "unknown"):
            confirm.append("MSE purchase preference / EMD exemption available if valid Udyam registration is obtained")
            if "Udyam Registration (for MSE benefits)" not in req_docs:
                req_docs.append("Udyam Registration (for MSE benefits)")

    # --- 2. GST requirement check ---
    gst_required = bool(
        (ei.get("gst_requirement") and str(ei.get("gst_requirement")).strip().lower() not in _NOT_STATED_VALS)
        or any("gst" in r.lower() for r in req_docs)
    )
    if gst_required:
        if "GST Registration" not in req_docs:
            req_docs.append("GST Registration")
        if profile.gst_status == "registered":
            satisfied.append("GST registration requirement appears satisfied")
        elif profile.gst_status == "not_registered":
            missing.append("GST registration is referenced in the source notice; business is currently not GST-registered")
        elif profile.gst_status == "exempt":
            confirm.append("Source mentions GST; verify whether GST-exempt businesses are permitted under tender terms")
        else:
            confirm.append("Confirm GST registration status against official tender requirements")

    # --- 3. PAN & Licences check ---
    pan_required = bool(
        (ei.get("pan_requirement") and str(ei.get("pan_requirement")).strip().lower() not in _NOT_STATED_VALS)
        or any(r.lower() == "pan" for r in req_docs)
    )
    if pan_required:
        if "pan" in profile_licences_low or profile.entity_type != "unregistered_individual":
            satisfied.append("PAN / formal business entity requirement aligns with profile")
        else:
            confirm.append("Confirm PAN availability for bid/application submission")

    # --- 4. OEM / Trader exclusion check ---
    comp_cond = (ei.get("company_registration") or "").lower()
    oem_only = "traders are excluded" in comp_cond or "must be the manufacturer / oem" in comp_cond
    if oem_only:
        if profile.business_type == "manufacturer" or any("oem" in l for l in profile_licences_low):
            satisfied.append("Manufacturer / OEM requirement aligns with business type")
        elif profile.business_type == "trader_distributor":
            hard_disqualifier = True
            missing.append("Source specifies Manufacturer/OEM requirement or excludes traders")
        else:
            confirm.append("Confirm OEM / manufacturer authorization requirement in official bid document")

    # --- 5. Turnover condition check (strictly distinguishing Bidder vs OEM turnover) ---
    bidder_turn_str = ei.get("bidder_turnover_conditions") or ""
    oem_turn_str = ei.get("oem_turnover_conditions") or ""
    turn_variant = ei.get("turnover_field_variant")
    if not bidder_turn_str and td and td.turnover_requirement and "oem average turnover" not in td.turnover_requirement.lower():
        bidder_turn_str = td.turnover_requirement

    bidder_req_lakhs = _parse_lakhs(bidder_turn_str)
    if bidder_req_lakhs is not None:
        if profile.annual_turnover_lakhs is None:
            confirm.append(f"Source specifies bidder average annual turnover of {bidder_req_lakhs:g} Lakh(s); profile turnover not provided")
        elif profile.annual_turnover_lakhs >= bidder_req_lakhs:
            satisfied.append(f"Annual turnover ({profile.annual_turnover_lakhs:g}L) meets stated bidder threshold ({bidder_req_lakhs:g}L)")
        elif mse_relaxation and profile.msme_udyam_status == "registered":
            satisfied.append(f"Turnover ({profile.annual_turnover_lakhs:g}L) is below {bidder_req_lakhs:g}L, but MSE turnover relaxation applies")
        else:
            hard_disqualifier = True
            missing.append(f"Published bidder turnover threshold ({bidder_req_lakhs:g} Lakh) exceeds profile turnover ({profile.annual_turnover_lakhs:g} Lakh)")

    oem_req_lakhs = _parse_lakhs(oem_turn_str)
    if oem_req_lakhs is not None:
        if profile.business_type == "manufacturer":
            if profile.annual_turnover_lakhs is None:
                confirm.append(f"Source specifies OEM Average Turnover (Last 3 Years) of {oem_req_lakhs:g} Lakh(s); confirm manufacturer turnover")
            elif profile.annual_turnover_lakhs >= oem_req_lakhs:
                satisfied.append(f"Manufacturer turnover meets OEM Average Turnover threshold ({oem_req_lakhs:g}L)")
            elif not (mse_relaxation and profile.msme_udyam_status == "registered"):
                hard_disqualifier = True
                missing.append(f"OEM Average Turnover threshold ({oem_req_lakhs:g}L) exceeds manufacturer turnover ({profile.annual_turnover_lakhs:g}L)")
        else:
            confirm.append(f"Source specifies OEM Average Turnover (Last 3 Years) of {oem_req_lakhs:g} Lakh(s) — confirm OEM partner meets this criteria")

    # --- 6. Experience condition check ---
    exp_str = (td.experience_requirement if td else "") or ""
    req_years = _parse_years(exp_str)
    if req_years is not None:
        if profile.years_of_experience is None:
            confirm.append(f"Source requires {req_years:g} year(s) of past experience; profile experience not provided")
        elif profile.years_of_experience >= req_years:
            satisfied.append(f"Business experience ({profile.years_of_experience:g} yrs) meets stated requirement ({req_years:g} yrs)")
        elif mse_relaxation and profile.msme_udyam_status == "registered":
            satisfied.append(f"Experience ({profile.years_of_experience:g} yrs) below {req_years:g} yrs, but MSE relaxation applies")
        else:
            hard_disqualifier = True
            missing.append(f"Published past experience requirement ({req_years:g} yrs) exceeds profile experience ({profile.years_of_experience:g} yrs)")

    # --- 7. Category-specific rules (Funding / Innovation Challenge / Jobs / Empanelment) ---
    if opp.category == "funding":
        if opp.subcategory == "innovation_challenge":
            if profile.business_type in ("startup", "service_provider", "manufacturer") or profile.business_stage in ("idea_pre_revenue", "early_stage", "micro", "small"):
                satisfied.append("Business stage/type aligns with innovation challenge / cohort funding")
            else:
                confirm.append("Verify stage/cohort eligibility in the official Innovation Challenge guidelines")
        else:
            if profile.business_stage in ("idea_pre_revenue", "early_stage", "micro", "small", "medium"):
                satisfied.append(f"Business stage ({profile.business_stage}) aligns with MSME/enterprise funding support")
            confirm.append("Verify beneficiary category and scheme-specific criteria on the official portal")

    if opp.category == "job":
        if profile.business_type == "individual_entrepreneur" or "job" in (profile.preferred_categories or []):
            confirm.append("Government recruitment notice — verify individual educational qualification and age limits in official notification")
        else:
            missing.append("Government individual recruitment notice (primarily for individual job seekers rather than registered businesses)")

    if td and td.tender_category == "Empanelment":
        satisfied.append("Vendor/agency empanelment opportunity suitable for qualified organisations")

    # --- 8. Ambiguous / Incomplete source check ---
    ambiguous = bool(ei.get("ambiguous_flag")) or (td and td.tender_status == TenderStatus.UNDER_VERIFICATION)
    if ambiguous:
        confirm.append("Official notice contains incomplete or 'As per Tender Document / ATC' eligibility terms — review full notice before applying")

    # --- Final Controlled Status Determination ---
    if hard_disqualifier:
        return EligibilityMatchStatus.NOT_ELIGIBLE.value, 0.0, satisfied, missing, confirm, req_docs

    if unverified or (td and td.tender_status == TenderStatus.UNDER_VERIFICATION):
        return EligibilityMatchStatus.REQUIRES_MANUAL_REVIEW.value, 0.50, satisfied, missing, confirm, req_docs

    if opp.category == "job" and profile.business_type != "individual_entrepreneur" and "job" not in (profile.preferred_categories or []):
        return EligibilityMatchStatus.NOT_ELIGIBLE.value, 0.10, satisfied, missing, confirm, req_docs

    if missing:
        return EligibilityMatchStatus.PARTIAL_MATCH.value, 0.65, satisfied, missing, confirm, req_docs

    if ambiguous and not satisfied:
        return EligibilityMatchStatus.REQUIRES_MANUAL_REVIEW.value, 0.50, satisfied, missing, confirm, req_docs

    if confirm and not satisfied:
        return EligibilityMatchStatus.INSUFFICIENT_INFORMATION.value, 0.55, satisfied, missing, confirm, req_docs

    if ambiguous:
        # Some conditions satisfied, but source has ATC/missing turnover-experience caveats
        return EligibilityMatchStatus.PARTIAL_MATCH.value, 0.70, satisfied, missing, confirm, req_docs

    if confirm and len(confirm) >= 2 and len(satisfied) <= 1:
        return EligibilityMatchStatus.INSUFFICIENT_INFORMATION.value, 0.55, satisfied, missing, confirm, req_docs

    if sector_score == 0.0:
        return EligibilityMatchStatus.PARTIAL_MATCH.value, 0.45, satisfied, missing, confirm, req_docs

    if confirm:
        return EligibilityMatchStatus.LIKELY_MATCH.value if len(satisfied) >= 1 else EligibilityMatchStatus.PARTIAL_MATCH.value, 0.90, satisfied, missing, confirm, req_docs

    return EligibilityMatchStatus.LIKELY_MATCH.value, 1.0, satisfied, missing, confirm, req_docs


def evaluate_match(
    profile: BusinessProfile,
    opp: Opportunity,
    config: MatchingConfig | None = None,
    *,
    today: dt.date | None = None,
) -> MatchEvaluation:
    """Computes transparent match score, factor breakdown, and eligibility intelligence."""
    today = today or dt.date.today()
    w_sector = config.sector_weight if (config and config.sector_weight is not None) else 30.0
    w_geo = config.geography_weight if (config and config.geography_weight is not None) else 20.0
    w_elig = config.eligibility_weight if (config and config.eligibility_weight is not None) else 25.0
    w_deadline = config.deadline_urgency_weight if (config and config.deadline_urgency_weight is not None) else 10.0
    w_cat = config.category_preference_weight if (config and config.category_preference_weight is not None) else 10.0
    w_ver = config.verification_weight if (config and config.verification_weight is not None) else 5.0
    total_w = max(1.0, w_sector + w_geo + w_elig + w_deadline + w_cat + w_ver)

    is_expired = _is_expired_or_closed(opp, today)
    is_published = opp.lifecycle_status in PUBLIC_STATUSES and not opp.is_fixture
    is_verified = opp.verification_status == VerificationStatus.OFFICIAL_CONFIRMED

    # 1. Sector & Capability
    s_sector, why_sector, rank_sector = _score_sector_and_capabilities(profile, opp)

    # 2. Geography
    s_geo, why_geo, geo_notes, rank_geo = _score_geography(profile, opp)

    # 3. Eligibility Intelligence
    elig_status, s_elig, satisfied, missing, confirm, req_docs = _evaluate_eligibility(
        profile, opp, is_expired=is_expired, sector_score=s_sector
    )
    if geo_notes:
        confirm.extend(geo_notes)

    # 4. Deadline Urgency
    if is_expired:
        s_deadline = 0.0
        dl_reason = "Expired or closed"
    elif opp.deadline:
        days_left = (opp.deadline - today).days
        if days_left <= 7:
            s_deadline = 1.0
            dl_reason = f"Closing soon ({days_left} day(s) remaining)"
        elif days_left <= 21:
            s_deadline = 0.85
            dl_reason = f"Active deadline ({days_left} days remaining)"
        else:
            s_deadline = 0.65
            dl_reason = f"Open deadline ({days_left} days remaining)"
    else:
        s_deadline = 0.40
        dl_reason = "Deadline not published"

    # 5. Category Preference
    prefs = [c.lower() for c in (profile.preferred_categories or ["tender", "funding", "job"])]
    if opp.category.lower() in prefs:
        s_cat = 1.0
        cat_reason = f"Matches preferred category ({opp.category})"
    else:
        s_cat = 0.20
        cat_reason = f"Outside preferred categories ({opp.category})"

    # 6. Verification Status
    if opp.verification_status == VerificationStatus.OFFICIAL_CONFIRMED:
        s_ver = 1.0
        ver_reason = "Verified against official source"
    elif opp.verification_status == VerificationStatus.OFFICIAL_UNVERIFIED_DETAILS:
        s_ver = 0.50
        ver_reason = "Official source found; details pending full verification"
    else:
        s_ver = 0.0
        ver_reason = f"Not officially confirmed ({opp.verification_status})"

    raw_score = (
        s_sector * w_sector
        + s_geo * w_geo
        + s_elig * w_elig
        + s_deadline * w_deadline
        + s_cat * w_cat
        + s_ver * w_ver
    ) * (100.0 / total_w)

    # Safety Caps:
    # 1. Expired/cancelled -> 0.0, never active recommendation
    if is_expired:
        final_score = 0.0
    else:
        final_score = round(raw_score, 1)
        if elig_status == EligibilityMatchStatus.NOT_ELIGIBLE.value:
            final_score = min(final_score, 25.0)
        if s_sector == 0.0:
            final_score = min(final_score, 35.0)
        if not is_verified:
            final_score = min(final_score, 40.0)

    is_active_rec = bool(
        is_published
        and not is_expired
        and is_verified
        and elig_status != EligibilityMatchStatus.NOT_ELIGIBLE.value
    )

    why_it_matches = why_sector + why_geo
    if opp.category.lower() in prefs:
        why_it_matches.append(f"Category '{opp.category}' is in your preferred opportunity categories")
    if not why_it_matches and not is_expired:
        why_it_matches.append("General public opportunity matching partial profile parameters")

    ranking_reasons = rank_sector + rank_geo + [dl_reason, cat_reason, ver_reason]

    breakdown = {
        "sector_and_capability": {"score": round(s_sector * 100, 1), "weight": w_sector, "weighted": round(s_sector * w_sector * 100 / total_w, 1)},
        "geography": {"score": round(s_geo * 100, 1), "weight": w_geo, "weighted": round(s_geo * w_geo * 100 / total_w, 1)},
        "eligibility": {"score": round(s_elig * 100, 1), "weight": w_elig, "weighted": round(s_elig * w_elig * 100 / total_w, 1)},
        "deadline_urgency": {"score": round(s_deadline * 100, 1), "weight": w_deadline, "weighted": round(s_deadline * w_deadline * 100 / total_w, 1)},
        "category_preference": {"score": round(s_cat * 100, 1), "weight": w_cat, "weighted": round(s_cat * w_cat * 100 / total_w, 1)},
        "source_verification": {"score": round(s_ver * 100, 1), "weight": w_ver, "weighted": round(s_ver * w_ver * 100 / total_w, 1)},
    }

    return MatchEvaluation(
        opportunity=opp,
        relevance_score=final_score,
        is_active_recommendation=is_active_rec,
        eligibility_status=elig_status,
        why_it_matches=why_it_matches,
        satisfied_conditions=satisfied,
        missing_requirements=missing,
        details_to_confirm=confirm,
        required_documents=req_docs,
        score_breakdown=breakdown,
        ranking_reasons=ranking_reasons,
    )


def rank_opportunities_for_profile(
    session: Session,
    profile: BusinessProfile,
    *,
    category: str | None = None,
    sector: str | None = None,
    state: str | None = None,
    eligibility_status: str | None = None,
    min_score: float | None = None,
    include_unpublished: bool = False,
    include_expired: bool = False,
    today: dt.date | None = None,
) -> list[MatchEvaluation]:
    """Ranks opportunities for a BusinessProfile.

    By default (`include_unpublished=False`, `include_expired=False`), strictly enforces the
    publication & verification workflow and excludes expired/unverified records.
    """
    today = today or dt.date.today()
    cfg = get_or_create_matching_config(session)
    threshold = min_score if min_score is not None else cfg.min_score_threshold

    stmt = select(Opportunity).where(Opportunity.is_fixture.is_(False))
    if not include_unpublished:
        stmt = stmt.where(
            Opportunity.lifecycle_status.in_(PUBLIC_STATUSES),
            Opportunity.verification_status == VerificationStatus.OFFICIAL_CONFIRMED,
        )
    if category:
        stmt = stmt.where(Opportunity.category == category)
    if state:
        if state.lower() == "national":
            stmt = stmt.where(Opportunity.state.is_(None))
        else:
            stmt = stmt.where(Opportunity.state == state)

    candidates = session.scalars(stmt).all()
    results: list[MatchEvaluation] = []
    for opp in candidates:
        if sector:
            opp_sec = (opp.tender_detail.sector if opp.tender_detail else opp.industry) or ""
            if opp_sec.lower() != sector.lower():
                continue
        if (not include_expired and cfg.exclude_expired) and _is_expired_or_closed(opp, today):
            continue

        ev = evaluate_match(profile, opp, cfg, today=today)
        if not include_unpublished and not ev.is_active_recommendation:
            # Exclude not_eligible / unverified / expired from active member feed unless explicitly filtered
            if eligibility_status and ev.eligibility_status == eligibility_status and not _is_expired_or_closed(opp, today):
                pass
            else:
                continue

        if eligibility_status and ev.eligibility_status != eligibility_status:
            continue
        if ev.relevance_score < threshold:
            continue
        results.append(ev)

    # Deterministic ranking: highest score first, earliest active deadline next, ID tie-breaker
    results.sort(
        key=lambda e: (
            -e.relevance_score,
            e.opportunity.deadline or dt.date(9999, 12, 31),
            e.opportunity.id,
        )
    )
    return results
