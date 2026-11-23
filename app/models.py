"""ORM models. Raw extracted content is stored separately from presentation fields."""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def new_id() -> str:
    return uuid.uuid4().hex


class TZDateTime(DateTime):
    """Always timezone-aware."""
    def __init__(self):
        super().__init__(timezone=True)


# --------------------------------------------------------------------------- Source registry
class Source(Base):
    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # stable slug, e.g. "tgpsc-whats-new"
    name: Mapped[str] = mapped_column(String(255))
    domain: Mapped[str] = mapped_column(String(255), index=True)
    url: Mapped[str] = mapped_column(String(1024))
    agent_id: Mapped[str] = mapped_column(String(64), index=True)
    parser: Mapped[str] = mapped_column(String(64))  # extractor key used by the agent
    config: Mapped[dict] = mapped_column(JSON, default=dict)  # private parser parameters (never public)
    categories: Mapped[list] = mapped_column(JSON, default=list)
    geographic_coverage: Mapped[list] = mapped_column(JSON, default=list)
    industry_relevance: Mapped[list] = mapped_column(JSON, default=list)
    collection_method: Mapped[str] = mapped_column(String(32))
    reliability: Mapped[str] = mapped_column(String(32))
    issuing_organisation: Mapped[str] = mapped_column(String(255))
    official_domains: Mapped[list] = mapped_column(JSON, default=list)  # domains legitimately owned by issuer
    support_status: Mapped[str] = mapped_column(String(16), default="untested")
    access_notes: Mapped[str] = mapped_column(Text, default="")
    scan_frequency_minutes: Mapped[int] = mapped_column(Integer, default=720)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    admin_notes: Mapped[str] = mapped_column(Text, default="")
    last_scan_at: Mapped[dt.datetime | None] = mapped_column(TZDateTime())
    last_success_at: Mapped[dt.datetime | None] = mapped_column(TZDateTime())
    last_failure_at: Mapped[dt.datetime | None] = mapped_column(TZDateTime())
    last_failure_reason: Mapped[str | None] = mapped_column(Text)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    next_scan_at: Mapped[dt.datetime | None] = mapped_column(TZDateTime())
    created_at: Mapped[dt.datetime] = mapped_column(TZDateTime(), default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(TZDateTime(), default=utcnow, onupdate=utcnow)


class SourceHistory(Base):
    """Audit trail of administrative changes to a source."""
    __tablename__ = "source_history"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), index=True)
    actor: Mapped[str] = mapped_column(String(128))
    change: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[dt.datetime] = mapped_column(TZDateTime(), default=utcnow)


# --------------------------------------------------------------------------- Scans
class ScanRun(Base):
    __tablename__ = "scan_runs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), index=True)
    agent_id: Mapped[str] = mapped_column(String(64), index=True)
    trigger: Mapped[str] = mapped_column(String(32), default="schedule")  # schedule | manual | retry
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    started_at: Mapped[dt.datetime | None] = mapped_column(TZDateTime())
    finished_at: Mapped[dt.datetime | None] = mapped_column(TZDateTime())
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    pages_visited: Mapped[list] = mapped_column(JSON, default=list)  # [{url, status, method, at}]
    items_seen: Mapped[int] = mapped_column(Integer, default=0)
    items_skipped: Mapped[int] = mapped_column(Integer, default=0)
    items_new: Mapped[int] = mapped_column(Integer, default=0)
    items_updated: Mapped[int] = mapped_column(Integer, default=0)
    items_unchanged: Mapped[int] = mapped_column(Integer, default=0)
    duplicates_detected: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    log: Mapped[list] = mapped_column(JSON, default=list)  # structured step log
    is_fixture: Mapped[bool] = mapped_column(Boolean, default=False)  # True when run against test fixtures


class RawCapture(Base):
    """Snapshot of fetched content (retention-limited)."""
    __tablename__ = "raw_captures"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scan_run_id: Mapped[str | None] = mapped_column(ForeignKey("scan_runs.id", ondelete="SET NULL"), index=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(String(2048))
    final_url: Mapped[str] = mapped_column(String(2048))
    method: Mapped[str] = mapped_column(String(16))  # http | browser
    http_status: Mapped[int | None] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    text_content: Mapped[str] = mapped_column(Text)  # visible text only, scripts stripped
    fetched_at: Mapped[dt.datetime] = mapped_column(TZDateTime(), default=utcnow)


class JobLock(Base):
    __tablename__ = "job_locks"
    name: Mapped[str] = mapped_column(String(128), primary_key=True)
    owner: Mapped[str] = mapped_column(String(128))
    expires_at: Mapped[dt.datetime] = mapped_column(TZDateTime())


# --------------------------------------------------------------------------- Opportunities
class Opportunity(Base):
    __tablename__ = "opportunities"
    __table_args__ = (
        UniqueConstraint("source_id", "external_key", name="uq_opp_source_key"),
        Index("ix_opp_public", "lifecycle_status", "category", "deadline"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    external_key: Mapped[str] = mapped_column(String(255))  # stable per-source identity
    slug: Mapped[str] = mapped_column(String(300), index=True)

    # Presentation (editable by admins)
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(32), index=True)
    subcategory: Mapped[str | None] = mapped_column(String(64))

    # Organisation
    issuing_organisation: Mapped[str] = mapped_column(String(255))
    publisher: Mapped[str] = mapped_column(String(255))
    source_type: Mapped[str] = mapped_column(String(32))  # SourceReliability
    source_name: Mapped[str] = mapped_column(String(255))

    # Location
    country: Mapped[str] = mapped_column(String(64), default="India")
    state: Mapped[str | None] = mapped_column(String(64), index=True)
    city: Mapped[str | None] = mapped_column(String(128))
    location_type: Mapped[str | None] = mapped_column(String(32))  # national | state | city | online

    # Details (only explicitly published values; NULL = not stated)
    industry: Mapped[str | None] = mapped_column(String(128))
    qualification: Mapped[str | None] = mapped_column(Text)
    experience: Mapped[str | None] = mapped_column(Text)
    eligibility: Mapped[str | None] = mapped_column(Text)
    benefits: Mapped[str | None] = mapped_column(Text)
    financial_details: Mapped[str | None] = mapped_column(Text)
    application_method: Mapped[str | None] = mapped_column(Text)
    reference_number: Mapped[str | None] = mapped_column(String(128), index=True)
    positions: Mapped[str | None] = mapped_column(String(64))

    # Dates
    published_date: Mapped[dt.date | None] = mapped_column(Date)
    opening_date: Mapped[dt.date | None] = mapped_column(Date)
    deadline: Mapped[dt.date | None] = mapped_column(Date)
    event_date: Mapped[dt.date | None] = mapped_column(Date)
    first_discovered_at: Mapped[dt.datetime] = mapped_column(TZDateTime(), default=utcnow)
    last_checked_at: Mapped[dt.datetime | None] = mapped_column(TZDateTime())
    last_updated_at: Mapped[dt.datetime] = mapped_column(TZDateTime(), default=utcnow)
    last_seen_in_source_at: Mapped[dt.datetime | None] = mapped_column(TZDateTime())

    # References
    original_url: Mapped[str] = mapped_column(String(2048))
    application_url: Mapped[str | None] = mapped_column(String(2048))
    supporting_documents: Mapped[list] = mapped_column(JSON, default=list)

    # Directive Unified Fields
    district: Mapped[str | None] = mapped_column(String(128), index=True)
    beneficiary_type: Mapped[str | None] = mapped_column(String(64))
    bc_relevance: Mapped[str] = mapped_column(String(64), index=True, default="general_open")
    opportunity_value: Mapped[float | None] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(16), default="INR")
    clean_title: Mapped[str | None] = mapped_column(String(500))
    original_document_reference: Mapped[str | None] = mapped_column(String(255))
    application_instructions: Mapped[str | None] = mapped_column(Text)
    amendment_detected_at: Mapped[dt.datetime | None] = mapped_column(TZDateTime())
    data_quality_score: Mapped[float] = mapped_column(Float, default=1.0)
    realtime_status: Mapped[str] = mapped_column(String(32), index=True, default="open")
    days_remaining: Mapped[int | None] = mapped_column(Integer)

    # Status
    lifecycle_status: Mapped[str] = mapped_column(String(32), index=True, default="discovered")
    verification_status: Mapped[str] = mapped_column(String(48), default="pending")
    expiry_status: Mapped[str] = mapped_column(String(24), default="date_unavailable")
    featured: Mapped[bool] = mapped_column(Boolean, default=False)

    # System
    agent_id: Mapped[str] = mapped_column(String(64), index=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), index=True)
    confidence: Mapped[str] = mapped_column(String(16), default="low")  # low | medium | high
    confidence_reasons: Mapped[list] = mapped_column(JSON, default=list)
    duplicate_group_id: Mapped[str | None] = mapped_column(String(32), index=True)
    duplicate_of_id: Mapped[str | None] = mapped_column(ForeignKey("opportunities.id"), index=True)
    merge_reason: Mapped[str | None] = mapped_column(Text)
    content_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    title_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    extracted_at: Mapped[dt.datetime] = mapped_column(TZDateTime(), default=utcnow)
    verified_at: Mapped[dt.datetime | None] = mapped_column(TZDateTime())
    needs_reverification: Mapped[bool] = mapped_column(Boolean, default=False)
    is_fixture: Mapped[bool] = mapped_column(Boolean, default=False)  # test data: never public

    # Raw (immutable as extracted from the source; never overwritten by edits)
    raw_title: Mapped[str] = mapped_column(Text)
    raw_text: Mapped[str] = mapped_column(Text)
    raw_fields: Mapped[dict] = mapped_column(JSON, default=dict)

    evidence: Mapped[list["Evidence"]] = relationship(back_populates="opportunity", cascade="all, delete-orphan")
    versions: Mapped[list["OpportunityVersion"]] = relationship(back_populates="opportunity", cascade="all, delete-orphan",
                                                                 order_by="OpportunityVersion.version")
    supporting_sources: Mapped[list["OpportunitySourceLink"]] = relationship(back_populates="opportunity",
                                                                             cascade="all, delete-orphan")
    tender_detail: Mapped["TenderDetail | None"] = relationship(
        back_populates="opportunity", uselist=False, cascade="all, delete-orphan"
    )
    scheme_detail: Mapped["SchemeDetail | None"] = relationship(
        back_populates="opportunity", uselist=False, cascade="all, delete-orphan"
    )



class Evidence(Base):
    """Per-claim evidence: where in the source text each extracted value was found."""
    __tablename__ = "evidence"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    opportunity_id: Mapped[str] = mapped_column(ForeignKey("opportunities.id", ondelete="CASCADE"), index=True)
    field: Mapped[str] = mapped_column(String(64))
    value: Mapped[str] = mapped_column(Text)
    snippet: Mapped[str] = mapped_column(Text)  # verbatim source text supporting the claim
    source_url: Mapped[str] = mapped_column(String(2048))
    found_in_source: Mapped[bool] = mapped_column(Boolean, default=True)
    captured_at: Mapped[dt.datetime] = mapped_column(TZDateTime(), default=utcnow)
    opportunity: Mapped[Opportunity] = relationship(back_populates="evidence")


class OpportunityVersion(Base):
    __tablename__ = "opportunity_versions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    opportunity_id: Mapped[str] = mapped_column(ForeignKey("opportunities.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSON)
    changed_fields: Mapped[list] = mapped_column(JSON, default=list)
    significant: Mapped[bool] = mapped_column(Boolean, default=False)
    reason: Mapped[str] = mapped_column(String(64))  # extracted | source_change | admin_edit
    actor: Mapped[str] = mapped_column(String(128), default="system")
    created_at: Mapped[dt.datetime] = mapped_column(TZDateTime(), default=utcnow)
    opportunity: Mapped[Opportunity] = relationship(back_populates="versions")


class OpportunitySourceLink(Base):
    """Primary + supporting sources for an opportunity (after duplicate merges)."""
    __tablename__ = "opportunity_sources"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    opportunity_id: Mapped[str] = mapped_column(ForeignKey("opportunities.id", ondelete="CASCADE"), index=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"))
    url: Mapped[str] = mapped_column(String(2048))
    role: Mapped[str] = mapped_column(String(16))  # primary | supporting
    reliability: Mapped[str] = mapped_column(String(32))
    added_at: Mapped[dt.datetime] = mapped_column(TZDateTime(), default=utcnow)
    opportunity: Mapped[Opportunity] = relationship(back_populates="supporting_sources")


class VerificationRecord(Base):
    """Internal verification results. Never exposed through the public API."""
    __tablename__ = "verification_records"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    opportunity_id: Mapped[str] = mapped_column(ForeignKey("opportunities.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(48))
    checks: Mapped[list] = mapped_column(JSON)  # [{name, passed, detail}]
    requires_human_review: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(TZDateTime(), default=utcnow)


class TenderDetail(Base):
    """1-to-1 extension table for government and institutional procurement tenders."""
    __tablename__ = "tender_details"

    opportunity_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("opportunities.id", ondelete="CASCADE"), primary_key=True
    )
    tender_id: Mapped[str | None] = mapped_column(String(128), index=True)
    reference_number: Mapped[str | None] = mapped_column(String(128), index=True)
    issuing_authority: Mapped[str] = mapped_column(String(255))
    department: Mapped[str] = mapped_column(String(255), default="Not stated")
    tender_category: Mapped[str] = mapped_column(String(64), default="Not stated")
    product_category: Mapped[str] = mapped_column(String(255), default="Not stated")
    sector: Mapped[str] = mapped_column(String(64), index=True, default="Other industries")
    estimated_value: Mapped[str] = mapped_column(String(128), default="Not published")
    emd_amount: Mapped[str] = mapped_column(String(128), default="Not published")
    tender_fee: Mapped[str] = mapped_column(String(128), default="Not published")
    document_download_date: Mapped[dt.date | None] = mapped_column(Date)
    pre_bid_date: Mapped[dt.date | None] = mapped_column(Date)
    pre_bid_details: Mapped[str] = mapped_column(Text, default="Not published")
    bid_opening_date: Mapped[dt.date | None] = mapped_column(Date)
    turnover_requirement: Mapped[str] = mapped_column(String(255), default="Not stated")
    experience_requirement: Mapped[str] = mapped_column(Text, default="Not stated")
    required_registrations: Mapped[list] = mapped_column(JSON, default=list)
    msme_preference: Mapped[str] = mapped_column(Text, default="Not stated")
    eligibility_intelligence: Mapped[dict] = mapped_column(JSON, default=dict)
    tender_status: Mapped[str] = mapped_column(String(32), index=True, default="open")
    corrigendum_history: Mapped[list] = mapped_column(JSON, default=list)
    cancellation_reason: Mapped[str | None] = mapped_column(Text)
    
    # Directive Section 17 Tender Intelligence Fields
    work_description: Mapped[str | None] = mapped_column(Text)
    tender_location: Mapped[str | None] = mapped_column(String(255))
    bid_submission_start: Mapped[dt.datetime | None] = mapped_column(TZDateTime())
    technical_bid_opening: Mapped[dt.datetime | None] = mapped_column(TZDateTime())
    required_certificates: Mapped[list] = mapped_column(JSON, default=list)
    document_page_evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    plain_language_summary: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[dt.datetime] = mapped_column(TZDateTime(), default=utcnow, onupdate=utcnow)

    opportunity: Mapped[Opportunity] = relationship(back_populates="tender_detail")


class SchemeDetail(Base):
    """1-to-1 extension table for Central, Telangana, and Andhra Pradesh Government Schemes."""
    __tablename__ = "scheme_details"

    opportunity_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("opportunities.id", ondelete="CASCADE"), primary_key=True
    )
    scheme_name: Mapped[str] = mapped_column(String(500))
    government_department: Mapped[str] = mapped_column(String(255))
    geographical_scope: Mapped[str] = mapped_column(String(32), index=True)  # pan_india | telangana | andhra_pradesh
    beneficiary_classification: Mapped[str] = mapped_column(String(64), index=True, default="other_eligible")
    beneficiary_categories: Mapped[list] = mapped_column(JSON, default=list)
    applicable_castes: Mapped[list] = mapped_column(JSON, default=list)
    domicile_required: Mapped[bool] = mapped_column(Boolean, default=False)
    domicile_state: Mapped[str | None] = mapped_column(String(64), index=True)
    income_limit: Mapped[str | None] = mapped_column(String(255))
    age_limit: Mapped[str | None] = mapped_column(String(128))
    education_requirement: Mapped[str | None] = mapped_column(Text)
    occupation_requirement: Mapped[str | None] = mapped_column(Text)
    business_eligibility: Mapped[str | None] = mapped_column(Text)
    benefit_type: Mapped[str] = mapped_column(String(64), default="other")
    benefit_amount: Mapped[str | None] = mapped_column(String(255))
    source_verification_status: Mapped[str] = mapped_column(String(32), index=True, default="verified")
    application_status: Mapped[str] = mapped_column(String(32), index=True, default="open")
    required_documents: Mapped[list] = mapped_column(JSON, default=list)
    official_application_url: Mapped[str | None] = mapped_column(String(2048))
    official_guideline_url: Mapped[str | None] = mapped_column(String(2048))
    last_verified_at: Mapped[dt.datetime | None] = mapped_column(TZDateTime(), default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(TZDateTime(), default=utcnow, onupdate=utcnow)

    opportunity: Mapped[Opportunity] = relationship(back_populates="scheme_detail")



# --------------------------------------------------------------------------- Admin
class AdminUser(Base):
    __tablename__ = "admin_users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="reviewer")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    token_version: Mapped[int] = mapped_column(Integer, default=0)  # bump to revoke all tokens
    created_at: Mapped[dt.datetime] = mapped_column(TZDateTime(), default=utcnow)
    last_login_at: Mapped[dt.datetime | None] = mapped_column(TZDateTime())


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor: Mapped[str] = mapped_column(String(128), index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    target_type: Mapped[str] = mapped_column(String(32))
    target_id: Mapped[str] = mapped_column(String(64), index=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(TZDateTime(), default=utcnow, index=True)


# --------------------------------------------------------------------------- Phase 3: Member Accounts & Business Profiles
class MemberAccount(Base):
    """Private BECCI member identity, strictly isolated from public opportunity data and admin users."""
    __tablename__ = "member_accounts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(128))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(TZDateTime(), default=utcnow)
    last_login_at: Mapped[dt.datetime | None] = mapped_column(TZDateTime())

    profile: Mapped[BusinessProfile | None] = relationship(
        back_populates="member", cascade="all, delete-orphan", uselist=False
    )


class BusinessProfile(Base):
    """Private BECCI member business profile capturing only attributes needed for opportunity matching."""
    __tablename__ = "business_profiles"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    member_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("member_accounts.id", ondelete="CASCADE"), unique=True, index=True
    )
    business_name: Mapped[str] = mapped_column(String(255))
    business_type: Mapped[str] = mapped_column(String(48), index=True)
    industry: Mapped[str | None] = mapped_column(String(128))
    becci_sector: Mapped[str] = mapped_column(String(64), index=True)
    secondary_sectors: Mapped[list] = mapped_column(JSON, default=list)
    state: Mapped[str] = mapped_column(String(64), index=True)
    district: Mapped[str | None] = mapped_column(String(128))
    business_stage: Mapped[str] = mapped_column(String(32), default="micro")
    msme_udyam_status: Mapped[str] = mapped_column(String(32), default="unknown")
    gst_status: Mapped[str] = mapped_column(String(32), default="unknown")
    entity_type: Mapped[str] = mapped_column(String(48), default="sole_proprietorship")
    annual_turnover_lakhs: Mapped[float | None] = mapped_column(Float)
    years_of_experience: Mapped[float | None] = mapped_column(Float)
    licences_and_registrations: Mapped[list] = mapped_column(JSON, default=list)
    capabilities: Mapped[list] = mapped_column(JSON, default=list)
    products_and_services: Mapped[list] = mapped_column(JSON, default=list)
    preferred_categories: Mapped[list] = mapped_column(JSON, default=lambda: ["tender", "funding", "job"])
    created_at: Mapped[dt.datetime] = mapped_column(TZDateTime(), default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(TZDateTime(), default=utcnow, onupdate=utcnow)

    member: Mapped[MemberAccount] = relationship(back_populates="profile")


class SavedOpportunity(Base):
    """Private per-member bookmarked opportunities."""
    __tablename__ = "saved_opportunities"
    __table_args__ = (UniqueConstraint("member_id", "opportunity_id", name="uq_saved_member_opp"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    member_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("member_accounts.id", ondelete="CASCADE"), index=True
    )
    opportunity_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("opportunities.id", ondelete="CASCADE"), index=True
    )
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(TZDateTime(), default=utcnow)


class OpportunityView(Base):
    """Private per-member viewed opportunity tracker."""
    __tablename__ = "opportunity_views"
    __table_args__ = (UniqueConstraint("member_id", "opportunity_id", name="uq_viewed_member_opp"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    member_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("member_accounts.id", ondelete="CASCADE"), index=True
    )
    opportunity_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("opportunities.id", ondelete="CASCADE"), index=True
    )
    view_count: Mapped[int] = mapped_column(Integer, default=1)
    first_viewed_at: Mapped[dt.datetime] = mapped_column(TZDateTime(), default=utcnow)
    last_viewed_at: Mapped[dt.datetime] = mapped_column(TZDateTime(), default=utcnow)


class MatchingConfig(Base):
    """Admin-configurable scoring weights and safety controls for the matching engine."""
    __tablename__ = "matching_configs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default="default")
    sector_weight: Mapped[float] = mapped_column(Float, default=30.0)
    geography_weight: Mapped[float] = mapped_column(Float, default=20.0)
    eligibility_weight: Mapped[float] = mapped_column(Float, default=25.0)
    deadline_urgency_weight: Mapped[float] = mapped_column(Float, default=10.0)
    category_preference_weight: Mapped[float] = mapped_column(Float, default=10.0)
    verification_weight: Mapped[float] = mapped_column(Float, default=5.0)
    min_score_threshold: Mapped[float] = mapped_column(Float, default=20.0)
    exclude_expired: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_by: Mapped[str] = mapped_column(String(64), default="system")
    updated_at: Mapped[dt.datetime] = mapped_column(TZDateTime(), default=utcnow, onupdate=utcnow)


class MatchFeedback(Base):
    """Admin feedback on recommendation quality (false-positive tracking & eligibility audit)."""
    __tablename__ = "match_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    business_profile_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("business_profiles.id", ondelete="CASCADE"), index=True
    )
    opportunity_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("opportunities.id", ondelete="CASCADE"), index=True
    )
    flag_type: Mapped[str] = mapped_column(String(32), index=True)
    reason: Mapped[str] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[dt.datetime] = mapped_column(TZDateTime(), default=utcnow)


class DLQRecord(Base):
    """Dead-letter queue for malformed, unparseable, or rejected records from scrapers and Apify webhooks."""
    __tablename__ = "dlq_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[str | None] = mapped_column(String(64), index=True)
    category: Mapped[str | None] = mapped_column(String(32), index=True)
    stage: Mapped[str] = mapped_column(String(64), index=True)  # e.g., "apify_webhook", "extraction", "validation", "security"
    error_reason: Mapped[str] = mapped_column(Text)
    raw_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(TZDateTime(), default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(TZDateTime(), default=utcnow, onupdate=utcnow)


class AIExtractionCache(Base):
    """Document-hash cache for AI extractions, eliminating redundant API spend."""
    __tablename__ = "ai_extraction_cache"

    cache_key: Mapped[str] = mapped_column(String(64), primary_key=True)  # sha256(f"{model}:{prompt_hash}")
    model: Mapped[str] = mapped_column(String(64), index=True)
    response_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(TZDateTime(), default=utcnow)


class AIUsageLog(Base):
    """Granular token consumption and cost audit per agent execution."""
    __tablename__ = "ai_usage_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[str] = mapped_column(String(64), index=True)
    model: Mapped[str] = mapped_column(String(64), index=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[dt.datetime] = mapped_column(TZDateTime(), default=utcnow)


class CentralSourceRegistry(Base):
    """Authoritative Central Source Registry as required by Directive Section 4."""
    __tablename__ = "central_source_registry"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    domain: Mapped[str] = mapped_column(String(255), index=True)
    source_type: Mapped[str] = mapped_column(String(64))  # official_government | psu | state_portal | corporate
    supported_categories: Mapped[list] = mapped_column(JSON, default=list)
    geographic_coverage: Mapped[list] = mapped_column(JSON, default=list)
    supported_methods: Mapped[list] = mapped_column(JSON, default=list)
    auth_requirements: Mapped[str] = mapped_column(String(64), default="none")
    update_frequency_minutes: Mapped[int] = mapped_column(Integer, default=720)
    last_successful_fetch: Mapped[dt.datetime | None] = mapped_column(TZDateTime())
    last_successful_verification: Mapped[dt.datetime | None] = mapped_column(TZDateTime())
    health_status: Mapped[str] = mapped_column(String(32), index=True, default="healthy")
    terms_notes: Mapped[str] = mapped_column(Text, default="")
    known_limitations: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(TZDateTime(), default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(TZDateTime(), default=utcnow, onupdate=utcnow)

