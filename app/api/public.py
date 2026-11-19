"""Public Versioned API (v1). Only approved and published records are exposed."""
from __future__ import annotations

import datetime as dt
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.enums import (
    BECCISector,
    BusinessStage,
    BusinessType,
    Category,
    EligibilityMatchStatus,
    EntityType,
    GSTStatus,
    LifecycleStatus,
    PUBLIC_STATUSES,
    RegistrationStatus,
    TenderStatus,
)
from app.models import Opportunity, SchemeDetail, Source, TenderDetail
from app.matching.schemes import evaluate_scheme_eligibility
from app.schemas import (
    CategoryCount,
    LocationCount,
    PublicOpportunityListResponse,
    PublicOpportunityOut,
    PublicSourceOut,
    SchemeEligibilityAssessmentOut,
)

router = APIRouter(prefix="/api/v1", tags=["Public Opportunity API"])


@router.get("/health", summary="Service health check")
def health_check(session: Session = Depends(get_db)):
    return {
        "status": "healthy",
        "service": "BECCI Opportunity Intelligence Engine",
        "version": "3.0.0",
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
    }


@router.get("/metadata", summary="Supported public filter & onboarding metadata")
def get_public_metadata(session: Session = Depends(get_db)):
    states = sorted(
        {
            r
            for r in session.scalars(
                select(Opportunity.state)
                .where(
                    Opportunity.lifecycle_status.in_(PUBLIC_STATUSES),
                    Opportunity.is_fixture.is_(False),
                    Opportunity.state.is_not(None),
                )
                .distinct()
            ).all()
            if r
        }
    )
    return {
        "categories": [c.value for c in Category],
        "sectors": [s.value for s in BECCISector],
        "states": ["National"] + states,
        "tender_statuses": [t.value for t in TenderStatus],
        "business_types": [b.value for b in BusinessType],
        "business_stages": [s.value for s in BusinessStage],
        "registration_statuses": [r.value for r in RegistrationStatus],
        "gst_statuses": [g.value for g in GSTStatus],
        "entity_types": [e.value for e in EntityType],
        "eligibility_statuses": [e.value for e in EligibilityMatchStatus],
    }


def _query_public_opportunities(
    session: Session,
    *,
    category: str | None = None,
    state: str | None = None,
    sector: str | None = None,
    tender_status: str | None = None,
    scope: str | None = None,
    beneficiary_category: str | None = None,
    beneficiary_classification: str | None = None,
    scheme_status: str | None = None,
    benefit_type: str | None = None,
    deadline_before: dt.date | None = None,
    deadline_after: dt.date | None = None,
    q: str | None = None,
    page: int = 1,
    limit: int = 20,
) -> PublicOpportunityListResponse:
    offset = (page - 1) * limit
    stmt = (
        select(Opportunity)
        .outerjoin(TenderDetail, Opportunity.id == TenderDetail.opportunity_id)
        .outerjoin(SchemeDetail, Opportunity.id == SchemeDetail.opportunity_id)
        .where(
            Opportunity.lifecycle_status.in_(PUBLIC_STATUSES),
            Opportunity.is_fixture.is_(False),
        )
    )

    if category:
        stmt = stmt.where(Opportunity.category == category)

    # Strict geographical filtering for schemes:
    # A Telangana user sees Pan-India schemes + Telangana-specific schemes.
    # An Andhra Pradesh user sees Pan-India schemes + AP-specific schemes.
    # Never show unrelated state-exclusive schemes in either set.
    # Jobs and Tenders remain PAN-INDIA.
    if category == "funding":
        if state:
            st_clean = state.strip().lower()
            if st_clean in ("telangana", "tg"):
                stmt = stmt.where(
                    or_(
                        SchemeDetail.geographical_scope.in_(["pan_india", "telangana"]),
                        Opportunity.state.in_(["Telangana", None]),
                    )
                )
            elif st_clean in ("andhra pradesh", "andhra", "ap"):
                stmt = stmt.where(
                    or_(
                        SchemeDetail.geographical_scope.in_(["pan_india", "andhra_pradesh"]),
                        Opportunity.state.in_(["Andhra Pradesh", None]),
                    )
                )
            elif st_clean == "national":
                stmt = stmt.where(
                    or_(
                        SchemeDetail.geographical_scope == "pan_india",
                        Opportunity.state.is_(None),
                    )
                )
            else:
                stmt = stmt.where(Opportunity.state == state)
    else:
        if state:
            if state.lower() == "national":
                stmt = stmt.where(Opportunity.state.is_(None))
            else:
                stmt = stmt.where(Opportunity.state == state)

    if scope:
        stmt = stmt.where(SchemeDetail.geographical_scope == scope.lower())
    if beneficiary_classification:
        stmt = stmt.where(SchemeDetail.beneficiary_classification == beneficiary_classification.lower())
    if scheme_status:
        stmt = stmt.where(SchemeDetail.application_status == scheme_status.lower())
    if benefit_type:
        stmt = stmt.where(SchemeDetail.benefit_type == benefit_type.lower())
    if beneficiary_category:
        stmt = stmt.where(SchemeDetail.beneficiary_categories.contains(beneficiary_category.lower()))
    if sector:
        stmt = stmt.where(
            or_(Opportunity.industry == sector, TenderDetail.sector == sector)
        )
    if tender_status:
        stmt = stmt.where(TenderDetail.tender_status == tender_status)
    if deadline_before:
        stmt = stmt.where(Opportunity.deadline <= deadline_before)
    if deadline_after:
        stmt = stmt.where(Opportunity.deadline >= deadline_after)
    if q:
        kw = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                Opportunity.title.ilike(kw),
                Opportunity.issuing_organisation.ilike(kw),
                Opportunity.reference_number.ilike(kw),
                TenderDetail.department.ilike(kw),
                TenderDetail.tender_id.ilike(kw),
            )
        )

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = session.scalar(count_stmt) or 0

    items_stmt = (
        stmt.order_by(Opportunity.deadline.asc().nullslast(), Opportunity.verified_at.desc())
        .offset(offset)
        .limit(limit)
    )
    items = session.scalars(items_stmt).all()

    return PublicOpportunityListResponse(
        items=[PublicOpportunityOut.model_validate(i) for i in items],
        total=total,
        page=page,
        limit=limit,
        has_more=(offset + len(items)) < total,
    )


@router.get("/opportunities", response_model=PublicOpportunityListResponse, summary="List verified public opportunities")
def list_opportunities(
    category: str | None = Query(None, description="Filter by category (job, funding, tender, etc.)"),
    state: str | None = Query(None, description="Filter by state (Telangana, Maharashtra, National, etc.)"),
    sector: str | None = Query(None, description="Filter by BECCI industry sector"),
    tender_status: str | None = Query(None, description="Filter tenders by status (open, closing_soon, extended, etc.)"),
    deadline_before: dt.date | None = Query(None, description="Filter opportunities with deadline on or before date"),
    deadline_after: dt.date | None = Query(None, description="Filter opportunities with deadline on or after date"),
    q: str | None = Query(None, description="Search title, issuing authority, department, or reference number"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    session: Session = Depends(get_db),
):
    return _query_public_opportunities(
        session,
        category=category,
        state=state,
        sector=sector,
        tender_status=tender_status,
        deadline_before=deadline_before,
        deadline_after=deadline_after,
        q=q,
        page=page,
        limit=limit,
    )


@router.get("/opportunities/closing-soon", response_model=list[PublicOpportunityOut], summary="Opportunities closing within 7 days")
def list_closing_soon(limit: int = Query(10, le=50), session: Session = Depends(get_db)):
    today = dt.date.today()
    next_week = today + dt.timedelta(days=7)
    stmt = (
        select(Opportunity)
        .where(
            Opportunity.lifecycle_status.in_(PUBLIC_STATUSES),
            Opportunity.is_fixture.is_(False),
            Opportunity.deadline >= today,
            Opportunity.deadline <= next_week,
        )
        .order_by(Opportunity.deadline.asc())
        .limit(limit)
    )
    items = session.scalars(stmt).all()
    return [PublicOpportunityOut.model_validate(i) for i in items]


@router.get("/opportunities/featured", response_model=list[PublicOpportunityOut], summary="Featured verified opportunities")
def list_featured(limit: int = Query(10, le=50), session: Session = Depends(get_db)):
    stmt = (
        select(Opportunity)
        .where(
            Opportunity.lifecycle_status.in_(PUBLIC_STATUSES),
            Opportunity.is_fixture.is_(False),
            Opportunity.featured.is_(True),
        )
        .order_by(Opportunity.verified_at.desc())
        .limit(limit)
    )
    items = session.scalars(stmt).all()
    return [PublicOpportunityOut.model_validate(i) for i in items]


@router.get("/opportunities/{id_or_slug}", response_model=PublicOpportunityOut, summary="Get public opportunity by ID or slug")
def get_opportunity(id_or_slug: str, session: Session = Depends(get_db)):
    stmt = (
        select(Opportunity)
        .where(
            (Opportunity.id == id_or_slug) | (Opportunity.slug == id_or_slug),
            Opportunity.lifecycle_status.in_(PUBLIC_STATUSES),
            Opportunity.is_fixture.is_(False),
        )
    )
    opp = session.scalars(stmt).first()
    if not opp:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Opportunity not found or not published")
    return PublicOpportunityOut.model_validate(opp)


# --------------------------------------------------------------------------- Dedicated Tender Endpoints
@router.get("/tenders", response_model=PublicOpportunityListResponse, summary="List verified public government & PSU tenders")
def list_public_tenders(
    state: str | None = Query(None, description="Filter by state (Telangana, Maharashtra, National, etc.)"),
    sector: str | None = Query(None, description="Filter by BECCI sector (Manufacturing, IT and technology, etc.)"),
    tender_status: str | None = Query(None, description="Filter by tender status (open, closing_soon, extended)"),
    deadline_before: dt.date | None = Query(None, description="Submission deadline on or before date (YYYY-MM-DD)"),
    deadline_after: dt.date | None = Query(None, description="Submission deadline on or after date (YYYY-MM-DD)"),
    q: str | None = Query(None, description="Search by department, ministry, title, or tender reference number"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    session: Session = Depends(get_db),
):
    return _query_public_opportunities(
        session,
        category="tender",
        state=state,
        sector=sector,
        tender_status=tender_status,
        deadline_before=deadline_before,
        deadline_after=deadline_after,
        q=q,
        page=page,
        limit=limit,
    )


@router.get("/tenders/{id_or_slug}", response_model=PublicOpportunityOut, summary="Get verified public tender details")
def get_public_tender(id_or_slug: str, session: Session = Depends(get_db)):
    stmt = (
        select(Opportunity)
        .where(
            Opportunity.category == "tender",
            (Opportunity.id == id_or_slug) | (Opportunity.slug == id_or_slug),
            Opportunity.lifecycle_status.in_(PUBLIC_STATUSES),
            Opportunity.is_fixture.is_(False),
        )
    )
    opp = session.scalars(stmt).first()
    if not opp:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tender not found or not published")
    return PublicOpportunityOut.model_validate(opp)


# --------------------------------------------------------------------------- Government Schemes Endpoints
class SchemeEligibilityCheckIn(BaseModel):
    domicile_state: str | None = None
    caste_community: str | None = None
    is_non_creamy_layer: bool | None = None
    annual_family_income: float | str | None = None
    age: int | None = None
    education: str | None = None
    occupation: str | None = None
    is_entrepreneur: bool | None = None
    gender: str | None = None


@router.get(
    "/schemes",
    response_model=PublicOpportunityListResponse,
    summary="List verified Central, Telangana, and AP government schemes",
)
def list_government_schemes(
    scope: str | None = Query(None, description="Geographical scope: pan_india, telangana, or andhra_pradesh"),
    state: str | None = Query(None, description="User state: Telangana, Andhra Pradesh, or National"),
    beneficiary_classification: str | None = Query(None, description="Classification: obc_bc_specific, general_msme, women_entrepreneurs, students, artisans, etc."),
    beneficiary_category: str | None = Query(None, description="Category tag: students, women, artisans, entrepreneurs, farmers, unemployed_youth, professionals"),
    application_status: str | None = Query(None, description="Application status: open, upcoming, closed, continuous, suspended"),
    benefit_type: str | None = Query(None, description="Benefit type: grant, subsidy, loan, scholarship, reimbursement, training"),
    q: str | None = Query(None, description="Search keyword in scheme name or issuing department"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    session: Session = Depends(get_db),
):
    return _query_public_opportunities(
        session,
        category="funding",
        state=state,
        scope=scope,
        beneficiary_classification=beneficiary_classification,
        beneficiary_category=beneficiary_category,
        scheme_status=application_status,
        benefit_type=benefit_type,
        q=q,
        page=page,
        limit=limit,
    )


@router.get("/schemes/{id_or_slug}", response_model=PublicOpportunityOut, summary="Get verified public scheme details")
def get_public_scheme(id_or_slug: str, session: Session = Depends(get_db)):
    stmt = (
        select(Opportunity)
        .where(
            Opportunity.category == "funding",
            (Opportunity.id == id_or_slug) | (Opportunity.slug == id_or_slug),
            Opportunity.lifecycle_status.in_(PUBLIC_STATUSES),
            Opportunity.is_fixture.is_(False),
        )
    )
    opp = session.scalars(stmt).first()
    if not opp:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scheme not found or not published")
    return PublicOpportunityOut.model_validate(opp)


@router.post(
    "/schemes/{id_or_slug}/check-eligibility",
    response_model=SchemeEligibilityAssessmentOut,
    summary="Advisory eligibility evaluation against official scheme rules",
)
def check_scheme_eligibility(
    id_or_slug: str,
    payload: SchemeEligibilityCheckIn,
    session: Session = Depends(get_db),
):
    stmt = (
        select(Opportunity)
        .where(
            Opportunity.category == "funding",
            (Opportunity.id == id_or_slug) | (Opportunity.slug == id_or_slug),
            Opportunity.lifecycle_status.in_(PUBLIC_STATUSES),
            Opportunity.is_fixture.is_(False),
        )
    )
    opp = session.scalars(stmt).first()
    if not opp or not opp.scheme_detail:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scheme or scheme eligibility specification not found",
        )
    return evaluate_scheme_eligibility(opp.scheme_detail, payload.model_dump())



@router.get("/categories", response_model=list[CategoryCount], summary="Opportunity counts per category")
def get_categories(session: Session = Depends(get_db)):
    stmt = (
        select(Opportunity.category, func.count(Opportunity.id))
        .where(Opportunity.lifecycle_status.in_(PUBLIC_STATUSES), Opportunity.is_fixture.is_(False))
        .group_by(Opportunity.category)
    )
    rows = session.execute(stmt).all()
    return [CategoryCount(category=r[0], count=r[1]) for r in rows]


@router.get("/locations", response_model=list[LocationCount], summary="Opportunity counts per geographic state")
def get_locations(session: Session = Depends(get_db)):
    stmt = (
        select(Opportunity.state, func.count(Opportunity.id))
        .where(Opportunity.lifecycle_status.in_(PUBLIC_STATUSES), Opportunity.is_fixture.is_(False))
        .group_by(Opportunity.state)
    )
    rows = session.execute(stmt).all()
    return [LocationCount(state=r[0] or "National", count=r[1]) for r in rows]


@router.get("/sources", response_model=list[PublicSourceOut], summary="List registered public discovery sources")
def list_public_sources(session: Session = Depends(get_db)):
    stmt = select(Source).where(Source.active.is_(True))
    sources = session.scalars(stmt).all()
    return [PublicSourceOut.model_validate(s) for s in sources]
