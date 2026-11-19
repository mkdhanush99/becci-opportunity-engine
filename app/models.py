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
