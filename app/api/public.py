"""Public Versioned API (v1). Only approved and published records are exposed."""
from __future__ import annotations

import datetime as dt
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.enums import LifecycleStatus, PUBLIC_STATUSES
from app.models import Opportunity, Source
from app.schemas import (
    CategoryCount,
    LocationCount,
    PublicOpportunityListResponse,
    PublicOpportunityOut,
    PublicSourceOut,
)

router = APIRouter(prefix="/api/v1", tags=["Public Opportunity API"])


@router.get("/health", summary="Service health check")
def health_check(session: Session = Depends(get_db)):
    return {
        "status": "healthy",
        "service": "BECCI Opportunity Intelligence Engine",
        "version": "1.0.0",
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
    }


@router.get("/opportunities", response_model=PublicOpportunityListResponse, summary="List verified public opportunities")
def list_opportunities(
    category: str | None = Query(None, description="Filter by category (job, funding, tender, etc.)"),
    state: str | None = Query(None, description="Filter by state (Telangana, Maharashtra, etc.)"),
    q: str | None = Query(None, description="Text search in title or issuing organisation"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    session: Session = Depends(get_db),
):
    offset = (page - 1) * limit
    stmt = (
        select(Opportunity)
        .where(
            Opportunity.lifecycle_status.in_(PUBLIC_STATUSES),
            Opportunity.is_fixture.is_(False)
        )
    )

    if category:
        stmt = stmt.where(Opportunity.category == category)
    if state:
        stmt = stmt.where(Opportunity.state == state)
    if q:
        kw = f"%{q.strip()}%"
        stmt = stmt.where(
            (Opportunity.title.ilike(kw)) | (Opportunity.issuing_organisation.ilike(kw))
        )

    # Count total
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = session.scalar(count_stmt) or 0

    # Sort: closing soon first, then recent verified
    items_stmt = stmt.order_by(Opportunity.deadline.asc().nullslast(), Opportunity.verified_at.desc()).offset(offset).limit(limit)
    items = session.scalars(items_stmt).all()

    return PublicOpportunityListResponse(
        items=[PublicOpportunityOut.model_validate(i) for i in items],
        total=total,
        page=page,
        limit=limit,
        has_more=(offset + len(items)) < total,
    )


@router.get("/opportunities/{id_or_slug}", response_model=PublicOpportunityOut, summary="Get public opportunity by ID or slug")
def get_opportunity(id_or_slug: str, session: Session = Depends(get_db)):
    stmt = (
        select(Opportunity)
        .where(
            (Opportunity.id == id_or_slug) | (Opportunity.slug == id_or_slug),
            Opportunity.lifecycle_status.in_(PUBLIC_STATUSES),
            Opportunity.is_fixture.is_(False)
        )
    )
    opp = session.scalars(stmt).first()
    if not opp:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Opportunity not found or not published")
    return PublicOpportunityOut.model_validate(opp)


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
