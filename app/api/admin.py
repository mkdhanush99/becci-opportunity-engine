"""Admin API: Human review workflow, source management, scan orchestration, and monitoring."""
from __future__ import annotations

from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.enums import AdminRole, LifecycleStatus
from app.models import AdminUser, Opportunity, ScanRun, Source, VerificationRecord
from app.orchestrator.service import Orchestrator
from app.pipeline.lifecycle import transition_lifecycle
from app.schemas import (
    AdminLoginRequest,
    AdminOpportunityDetailOut,
    AdminOpportunityReviewRequest,
    AdminTokenResponse,
    PublicOpportunityOut,
    ScanRunOut,
    SourceOut,
    SystemMetricsOut,
)
from app.security.auth import (
    generate_token,
    get_current_admin,
    require_role,
    verify_password,
)

router = APIRouter(prefix="/api/admin", tags=["Administrator Workflow & Control"])


# --------------------------------------------------------------------------- Authentication
@router.post("/auth/login", response_model=AdminTokenResponse, summary="Admin login")
def login(req: AdminLoginRequest, session: Session = Depends(get_db)):
    stmt = select(AdminUser).where(AdminUser.username == req.username, AdminUser.active.is_(True))
    admin = session.scalars(stmt).first()
    if not admin or not verify_password(req.password, admin.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    token = generate_token(admin.username, admin.role, admin.token_version)
    return AdminTokenResponse(access_token=token, role=admin.role, username=admin.username)


# --------------------------------------------------------------------------- Human Review Queue
@router.get("/queue", response_model=list[PublicOpportunityOut], summary="List opportunities pending human review")
def get_review_queue(
    current_admin: Annotated[AdminUser, Depends(require_role(AdminRole.REVIEWER))],
    category: str | None = None,
    limit: int = Query(50, le=100),
    session: Session = Depends(get_db),
):
    stmt = select(Opportunity).where(
        Opportunity.lifecycle_status.in_([LifecycleStatus.NEEDS_HUMAN_REVIEW, LifecycleStatus.AWAITING_VERIFICATION])
    )
    if category:
        stmt = stmt.where(Opportunity.category == category)
    stmt = stmt.order_by(Opportunity.extracted_at.desc()).limit(limit)
    items = session.scalars(stmt).all()
    return [PublicOpportunityOut.model_validate(i) for i in items]


@router.get("/opportunities/{opp_id}", response_model=AdminOpportunityDetailOut, summary="Inspect extracted opportunity & evidence")
def get_opportunity_detail(
    opp_id: str,
    current_admin: Annotated[AdminUser, Depends(require_role(AdminRole.REVIEWER))],
    session: Session = Depends(get_db),
):
    opp = session.get(Opportunity, opp_id)
    if not opp:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Opportunity not found")

    # Fetch verification records
    v_stmt = select(VerificationRecord).where(VerificationRecord.opportunity_id == opp.id).order_by(VerificationRecord.created_at.desc())
    v_records = session.scalars(v_stmt).all()

    detail = AdminOpportunityDetailOut.model_validate(opp)
    detail.verification_records = v_records
    return detail


@router.post("/opportunities/{opp_id}/review", response_model=PublicOpportunityOut, summary="Approve, reject, publish or edit presentation wording")
def review_opportunity(
    opp_id: str,
    req: AdminOpportunityReviewRequest,
    current_admin: Annotated[AdminUser, Depends(require_role(AdminRole.REVIEWER))],
    session: Session = Depends(get_db),
):
    opp = session.get(Opportunity, opp_id)
    if not opp:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Opportunity not found")

    # Apply presentation field edits if provided
    if req.title is not None:
        opp.title = req.title.strip()
    if req.description is not None:
        opp.description = req.description.strip()
    if req.eligibility is not None:
        opp.eligibility = req.eligibility.strip()
    if req.deadline is not None:
        opp.deadline = req.deadline

    target_status = {
        "approve": LifecycleStatus.APPROVED,
        "publish": LifecycleStatus.PUBLISHED,
        "reject": LifecycleStatus.REJECTED,
        "unpublish": LifecycleStatus.NEEDS_HUMAN_REVIEW,
        "mark_expired": LifecycleStatus.EXPIRED,
    }.get(req.action.lower())

    if not target_status:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unsupported review action '{req.action}'")

    transition_lifecycle(session, opp, target_status, actor=current_admin.username, reason=req.reason, force=True)
    session.commit()
    return PublicOpportunityOut.model_validate(opp)


# --------------------------------------------------------------------------- Scan Orchestration
@router.post("/sources/{source_id}/scan", response_model=ScanRunOut, summary="Trigger manual source scan")
def trigger_scan(
    source_id: str,
    current_admin: Annotated[AdminUser, Depends(require_role(AdminRole.ADMIN))],
    session: Session = Depends(get_db),
):
    orchestrator = Orchestrator(session)
    scan_run = orchestrator.run_source_scan(source_id=source_id, trigger=f"admin:{current_admin.username}")
    return ScanRunOut.model_validate(scan_run)


@router.get("/scans", response_model=list[ScanRunOut], summary="List recent scan runs")
def list_scans(
    current_admin: Annotated[AdminUser, Depends(require_role(AdminRole.REVIEWER))],
    limit: int = Query(25, le=100),
    session: Session = Depends(get_db),
):
    stmt = select(ScanRun).order_by(ScanRun.started_at.desc()).limit(limit)
    scans = session.scalars(stmt).all()
    return [ScanRunOut.model_validate(s) for s in scans]


# --------------------------------------------------------------------------- Sources Management
@router.get("/sources", response_model=list[SourceOut], summary="List all source records")
def list_sources(
    current_admin: Annotated[AdminUser, Depends(require_role(AdminRole.VIEWER))],
    session: Session = Depends(get_db),
):
    stmt = select(Source).order_by(Source.id.asc())
    sources = session.scalars(stmt).all()
    return [SourceOut.model_validate(s) for s in sources]


# --------------------------------------------------------------------------- Monitoring & Metrics
@router.get("/metrics", response_model=SystemMetricsOut, summary="System-wide operational metrics")
def get_metrics(
    current_admin: Annotated[AdminUser, Depends(require_role(AdminRole.VIEWER))],
    session: Session = Depends(get_db),
):
    total_src = session.scalar(select(func.count(Source.id))) or 0
    active_src = session.scalar(select(func.count(Source.id)).where(Source.active.is_(True))) or 0
    supp_src = session.scalar(select(func.count(Source.id)).where(Source.support_status == "supported")) or 0
    unsupp_src = session.scalar(select(func.count(Source.id)).where(Source.support_status == "unsupported")) or 0

    total_scans = session.scalar(select(func.count(ScanRun.id))) or 0
    succ_scans = session.scalar(select(func.count(ScanRun.id)).where(ScanRun.status == "success")) or 0
    fail_scans = session.scalar(select(func.count(ScanRun.id)).where(ScanRun.status.in_(["failed", "blocked"]))) or 0

    total_opps = session.scalar(select(func.count(Opportunity.id))) or 0
    pub_opps = session.scalar(select(func.count(Opportunity.id)).where(Opportunity.lifecycle_status == LifecycleStatus.PUBLISHED)) or 0
    review_opps = session.scalar(select(func.count(Opportunity.id)).where(Opportunity.lifecycle_status == LifecycleStatus.NEEDS_HUMAN_REVIEW)) or 0
    exp_opps = session.scalar(select(func.count(Opportunity.id)).where(Opportunity.lifecycle_status == LifecycleStatus.EXPIRED)) or 0
    dups = session.scalar(select(func.sum(ScanRun.duplicates_detected))) or 0

    return SystemMetricsOut(
        total_sources=total_src,
        active_sources=active_src,
        supported_sources=supp_src,
        unsupported_sources=unsupp_src,
        total_scans=total_scans,
        successful_scans=succ_scans,
        failed_scans=fail_scans,
        total_opportunities=total_opps,
        published_opportunities=pub_opps,
        pending_review_opportunities=review_opps,
        expired_opportunities=exp_opps,
        duplicates_merged=int(dups),
    )
