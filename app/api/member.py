"""Private BECCI Member API (v1): Business Profiles, Personalised Matching, Saved & Viewed Tracking.

Strictly isolated from Public API and Admin API:
- Requires valid member bearer token (`member|...`)
- Every operation is scoped to `current_member.id`
- Recommendations strictly respect the existing publication & verification workflow
"""
from __future__ import annotations

from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.enums import (
    BECCISector,
    BusinessStage,
    BusinessType,
    Category,
    EntityType,
    GSTStatus,
    PUBLIC_STATUSES,
    RegistrationStatus,
)
from app.matching.engine import (
    MatchEvaluation,
    evaluate_match,
    get_or_create_matching_config,
    rank_opportunities_for_profile,
)
from app.models import (
    BusinessProfile,
    MemberAccount,
    Opportunity,
    OpportunityView,
    SavedOpportunity,
    utcnow,
)
from app.schemas import (
    BusinessProfileIn,
    BusinessProfileOut,
    EligibilityExplanationOut,
    MemberLoginRequest,
    MemberRegisterRequest,
    MemberTokenResponse,
    OpportunityMatchOut,
    PublicOpportunityOut,
    RecommendationListResponse,
    SaveOpportunityRequest,
    SavedOpportunityOut,
    ViewedOpportunityOut,
)
from app.security.auth import (
    generate_member_token,
    get_current_member,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/api/v1/member", tags=["Member Business Profile & Matching API"])

_VALID_SECTORS = {s.value for s in BECCISector}
_VALID_TYPES = {t.value for t in BusinessType}
_VALID_STAGES = {s.value for s in BusinessStage}
_VALID_REG = {r.value for r in RegistrationStatus}
_VALID_GST = {g.value for g in GSTStatus}
_VALID_ENTITIES = {e.value for e in EntityType}
_VALID_CATS = {c.value for c in Category}


def _validate_profile_enums(req: BusinessProfileIn) -> None:
    if req.becci_sector not in _VALID_SECTORS:
        raise HTTPException(status_code=422, detail=f"Invalid becci_sector '{req.becci_sector}'. Must be one of {sorted(_VALID_SECTORS)}")
    for sec in req.secondary_sectors:
        if sec not in _VALID_SECTORS:
            raise HTTPException(status_code=422, detail=f"Invalid secondary sector '{sec}'")
    if req.business_type not in _VALID_TYPES:
        raise HTTPException(status_code=422, detail=f"Invalid business_type '{req.business_type}'")
    if req.business_stage not in _VALID_STAGES:
        raise HTTPException(status_code=422, detail=f"Invalid business_stage '{req.business_stage}'")
    if req.msme_udyam_status not in _VALID_REG:
        raise HTTPException(status_code=422, detail=f"Invalid msme_udyam_status '{req.msme_udyam_status}'")
    if req.gst_status not in _VALID_GST:
        raise HTTPException(status_code=422, detail=f"Invalid gst_status '{req.gst_status}'")
    if req.entity_type not in _VALID_ENTITIES:
        raise HTTPException(status_code=422, detail=f"Invalid entity_type '{req.entity_type}'")
    for cat in req.preferred_categories:
        if cat not in _VALID_CATS:
            raise HTTPException(status_code=422, detail=f"Invalid preferred category '{cat}'")


def _to_match_out(
    ev: MatchEvaluation,
    saved_ids: set[str],
    viewed_ids: set[str],
) -> OpportunityMatchOut:
    return OpportunityMatchOut(
        opportunity=PublicOpportunityOut.model_validate(ev.opportunity),
        relevance_score=ev.relevance_score,
        is_active_recommendation=ev.is_active_recommendation,
        eligibility=EligibilityExplanationOut(
            eligibility_status=ev.eligibility_status,
            why_it_matches=ev.why_it_matches,
            satisfied_conditions=ev.satisfied_conditions,
            missing_requirements=ev.missing_requirements,
            details_to_confirm=ev.details_to_confirm,
            required_documents=ev.required_documents,
            disclaimer=ev.disclaimer,
        ),
        score_breakdown=ev.score_breakdown,
        ranking_reasons=ev.ranking_reasons,
        is_saved=ev.opportunity.id in saved_ids,
        is_viewed=ev.opportunity.id in viewed_ids,
    )


# --------------------------------------------------------------------------- Member Authentication
@router.post("/auth/register", response_model=MemberTokenResponse, status_code=status.HTTP_201_CREATED, summary="Register BECCI member account")
def register_member(req: MemberRegisterRequest, session: Session = Depends(get_db)):
    email = req.email.strip().lower()
    existing = session.scalars(select(MemberAccount).where(MemberAccount.email == email)).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An account with this email already exists")

    member = MemberAccount(
        email=email,
        password_hash=hash_password(req.password),
        display_name=req.display_name.strip(),
        active=True,
        created_at=utcnow(),
    )
    session.add(member)
    session.commit()
    session.refresh(member)

    token = generate_member_token(member.id, member.token_version)
    return MemberTokenResponse(
        access_token=token,
        member_id=member.id,
        email=member.email,
        display_name=member.display_name,
    )


@router.post("/auth/login", response_model=MemberTokenResponse, summary="BECCI member login")
def login_member(req: MemberLoginRequest, session: Session = Depends(get_db)):
    email = req.email.strip().lower()
    member = session.scalars(
        select(MemberAccount).where(MemberAccount.email == email, MemberAccount.active.is_(True))
    ).first()
    if not member or not verify_password(req.password, member.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    member.last_login_at = utcnow()
    session.commit()
    token = generate_member_token(member.id, member.token_version)
    return MemberTokenResponse(
        access_token=token,
        member_id=member.id,
        email=member.email,
        display_name=member.display_name,
    )


# --------------------------------------------------------------------------- Business Profile CRUD
@router.post("/profile", response_model=BusinessProfileOut, summary="Create or update authenticated member's business profile")
@router.put("/profile", response_model=BusinessProfileOut, summary="Update authenticated member's business profile")
def upsert_profile(
    req: BusinessProfileIn,
    current_member: Annotated[MemberAccount, Depends(get_current_member)],
    session: Session = Depends(get_db),
):
    _validate_profile_enums(req)
    profile = session.scalars(
        select(BusinessProfile).where(BusinessProfile.member_id == current_member.id)
    ).first()

    now = utcnow()
    if not profile:
        profile = BusinessProfile(member_id=current_member.id, created_at=now, updated_at=now, **req.model_dump())
        session.add(profile)
    else:
        for k, v in req.model_dump().items():
            setattr(profile, k, v)
        profile.updated_at = now

    session.commit()
    session.refresh(profile)
    return BusinessProfileOut.model_validate(profile)


@router.get("/profile", response_model=BusinessProfileOut, summary="Retrieve authenticated member's business profile")
def get_profile(
    current_member: Annotated[MemberAccount, Depends(get_current_member)],
    session: Session = Depends(get_db),
):
    profile = session.scalars(
        select(BusinessProfile).where(BusinessProfile.member_id == current_member.id)
    ).first()
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Business profile not yet created")
    return BusinessProfileOut.model_validate(profile)


# --------------------------------------------------------------------------- Personalised Recommendations & Match Explanation
@router.get("/recommendations", response_model=RecommendationListResponse, summary="Get personalised ranked opportunities")
def get_recommendations(
    current_member: Annotated[MemberAccount, Depends(get_current_member)],
    category: str | None = Query(None, description="Filter by category (tender, funding, job)"),
    sector: str | None = Query(None, description="Filter by BECCI sector"),
    state: str | None = Query(None, description="Filter by state or 'National'"),
    eligibility_status: str | None = Query(None, description="Filter by eligibility status"),
    min_score: float | None = Query(None, ge=0.0, le=100.0),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    session: Session = Depends(get_db),
):
    profile = session.scalars(
        select(BusinessProfile).where(BusinessProfile.member_id == current_member.id)
    ).first()
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Create a business profile first at POST /api/v1/member/profile",
        )

    ranked = rank_opportunities_for_profile(
        session,
        profile,
        category=category,
        sector=sector,
        state=state,
        eligibility_status=eligibility_status,
        min_score=min_score,
        include_unpublished=False,
        include_expired=False,
    )

    saved_ids = set(
        session.scalars(select(SavedOpportunity.opportunity_id).where(SavedOpportunity.member_id == current_member.id)).all()
    )
    viewed_ids = set(
        session.scalars(select(OpportunityView.opportunity_id).where(OpportunityView.member_id == current_member.id)).all()
    )

    total = len(ranked)
    offset = (page - 1) * limit
    page_items = [_to_match_out(ev, saved_ids, viewed_ids) for ev in ranked[offset : offset + limit]]

    return RecommendationListResponse(
        profile_id=profile.id,
        business_name=profile.business_name,
        items=page_items,
        total=total,
        page=page,
        limit=limit,
        has_more=(offset + len(page_items)) < total,
    )


@router.get("/opportunities/{opp_id}/match", response_model=OpportunityMatchOut, summary="View match explanation for a specific published opportunity")
def get_opportunity_match_explanation(
    opp_id: str,
    current_member: Annotated[MemberAccount, Depends(get_current_member)],
    session: Session = Depends(get_db),
):
    profile = session.scalars(
        select(BusinessProfile).where(BusinessProfile.member_id == current_member.id)
    ).first()
    if not profile:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Create a business profile first")

    opp = session.scalars(
        select(Opportunity).where(
            Opportunity.id == opp_id,
            Opportunity.lifecycle_status.in_(PUBLIC_STATUSES),
            Opportunity.is_fixture.is_(False),
        )
    ).first()
    if not opp:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Published opportunity not found")

    cfg = get_or_create_matching_config(session)
    ev = evaluate_match(profile, opp, cfg)
    saved = session.scalars(
        select(SavedOpportunity.opportunity_id).where(
            SavedOpportunity.member_id == current_member.id,
            SavedOpportunity.opportunity_id == opp_id,
        )
    ).first()
    viewed = session.scalars(
        select(OpportunityView.opportunity_id).where(
            OpportunityView.member_id == current_member.id,
            OpportunityView.opportunity_id == opp_id,
        )
    ).first()
    return _to_match_out(ev, {saved} if saved else set(), {viewed} if viewed else set())


# --------------------------------------------------------------------------- Saved & Viewed Opportunity Tracking
@router.post("/saved/{opp_id}", response_model=SavedOpportunityOut, status_code=status.HTTP_201_CREATED, summary="Save an opportunity")
def save_opportunity(
    opp_id: str,
    current_member: Annotated[MemberAccount, Depends(get_current_member)],
    req: SaveOpportunityRequest | None = None,
    session: Session = Depends(get_db),
):
    opp = session.scalars(
        select(Opportunity).where(
            Opportunity.id == opp_id,
            Opportunity.lifecycle_status.in_(PUBLIC_STATUSES),
            Opportunity.is_fixture.is_(False),
        )
    ).first()
    if not opp:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Published opportunity not found")

    existing = session.scalars(
        select(SavedOpportunity).where(
            SavedOpportunity.member_id == current_member.id,
            SavedOpportunity.opportunity_id == opp_id,
        )
    ).first()
    notes = req.notes if req else None
    if existing:
        if notes is not None:
            existing.notes = notes
        rec = existing
    else:
        rec = SavedOpportunity(member_id=current_member.id, opportunity_id=opp_id, notes=notes, created_at=utcnow())
        session.add(rec)
    session.commit()
    session.refresh(rec)
    return SavedOpportunityOut(
        opportunity_id=opp.id,
        notes=rec.notes,
        saved_at=rec.created_at,
        opportunity=PublicOpportunityOut.model_validate(opp),
    )


@router.delete("/saved/{opp_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove a saved opportunity")
def unsave_opportunity(
    opp_id: str,
    current_member: Annotated[MemberAccount, Depends(get_current_member)],
    session: Session = Depends(get_db),
):
    existing = session.scalars(
        select(SavedOpportunity).where(
            SavedOpportunity.member_id == current_member.id,
            SavedOpportunity.opportunity_id == opp_id,
        )
    ).first()
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Saved opportunity not found")
    session.delete(existing)
    session.commit()


@router.get("/saved", response_model=list[SavedOpportunityOut], summary="List authenticated member's saved opportunities")
def list_saved_opportunities(
    current_member: Annotated[MemberAccount, Depends(get_current_member)],
    session: Session = Depends(get_db),
):
    rows = session.scalars(
        select(SavedOpportunity)
        .where(SavedOpportunity.member_id == current_member.id)
        .order_by(SavedOpportunity.created_at.desc())
    ).all()
    out: list[SavedOpportunityOut] = []
    for r in rows:
        opp = session.get(Opportunity, r.opportunity_id)
        if opp and opp.lifecycle_status in PUBLIC_STATUSES and not opp.is_fixture:
            out.append(
                SavedOpportunityOut(
                    opportunity_id=opp.id,
                    notes=r.notes,
                    saved_at=r.created_at,
                    opportunity=PublicOpportunityOut.model_validate(opp),
                )
            )
    return out


@router.post("/viewed/{opp_id}", response_model=ViewedOpportunityOut, summary="Record that member viewed an opportunity")
def record_viewed_opportunity(
    opp_id: str,
    current_member: Annotated[MemberAccount, Depends(get_current_member)],
    session: Session = Depends(get_db),
):
    opp = session.scalars(
        select(Opportunity).where(
            Opportunity.id == opp_id,
            Opportunity.lifecycle_status.in_(PUBLIC_STATUSES),
            Opportunity.is_fixture.is_(False),
        )
    ).first()
    if not opp:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Published opportunity not found")

    now = utcnow()
    rec = session.scalars(
        select(OpportunityView).where(
            OpportunityView.member_id == current_member.id,
            OpportunityView.opportunity_id == opp_id,
        )
    ).first()
    if rec:
        rec.view_count += 1
        rec.last_viewed_at = now
    else:
        rec = OpportunityView(
            member_id=current_member.id,
            opportunity_id=opp_id,
            view_count=1,
            first_viewed_at=now,
            last_viewed_at=now,
        )
        session.add(rec)
    session.commit()
    session.refresh(rec)
    return ViewedOpportunityOut(
        opportunity_id=opp.id,
        view_count=rec.view_count,
        first_viewed_at=rec.first_viewed_at,
        last_viewed_at=rec.last_viewed_at,
        opportunity=PublicOpportunityOut.model_validate(opp),
    )


@router.get("/viewed", response_model=list[ViewedOpportunityOut], summary="List authenticated member's viewed opportunities")
def list_viewed_opportunities(
    current_member: Annotated[MemberAccount, Depends(get_current_member)],
    limit: int = Query(50, ge=1, le=200),
    session: Session = Depends(get_db),
):
    rows = session.scalars(
        select(OpportunityView)
        .where(OpportunityView.member_id == current_member.id)
        .order_by(OpportunityView.last_viewed_at.desc())
        .limit(limit)
    ).all()
    out: list[ViewedOpportunityOut] = []
    for r in rows:
        opp = session.get(Opportunity, r.opportunity_id)
        if opp and opp.lifecycle_status in PUBLIC_STATUSES and not opp.is_fixture:
            out.append(
                ViewedOpportunityOut(
                    opportunity_id=opp.id,
                    view_count=r.view_count,
                    first_viewed_at=r.first_viewed_at,
                    last_viewed_at=r.last_viewed_at,
                    opportunity=PublicOpportunityOut.model_validate(opp),
                )
            )
    return out
