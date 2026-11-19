"""Pydantic schemas for Public and Admin APIs."""
from __future__ import annotations

import datetime as dt
from pydantic import BaseModel, ConfigDict, Field


STANDARD_DISCLAIMER = (
    "BECCI provides this information for discovery and awareness. Opportunities are published by their "
    "respective issuing organisations. Please review the original notification and verify eligibility, "
    "dates and requirements before applying. BECCI does not guarantee selection, funding, approval or employment."
)


# --------------------------------------------------------------------------- Public Schemas
class PublicOpportunityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    slug: str
    title: str
    description: str | None
    category: str
    subcategory: str | None

    issuing_organisation: str
    publisher: str
    source_type: str

    country: str
    state: str | None
    city: str | None
    location_type: str | None

    industry: str | None
    qualification: str | None
    experience: str | None
    eligibility: str | None
    benefits: str | None
    financial_details: str | None
    application_method: str | None
    reference_number: str | None
    positions: str | None

    published_date: dt.date | None
    opening_date: dt.date | None
    deadline: dt.date | None
    event_date: dt.date | None
    last_verified_at: dt.datetime | None = Field(alias="verified_at")

    original_url: str
    application_url: str | None
    supporting_documents: list[dict] = Field(default_factory=list)

    lifecycle_status: str
    expiry_status: str
    disclaimer: str = STANDARD_DISCLAIMER


class PublicOpportunityListResponse(BaseModel):
    items: list[PublicOpportunityOut]
    total: int
    page: int
    limit: int
    has_more: bool


class CategoryCount(BaseModel):
    category: str
    count: int


class LocationCount(BaseModel):
    state: str | None
    count: int


class PublicSourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    domain: str
    reliability: str
    geographic_coverage: list[str]
    issuing_organisation: str


# --------------------------------------------------------------------------- Admin Schemas
class AdminLoginRequest(BaseModel):
    username: str
    password: str


class AdminTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    username: str


class EvidenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    field: str
    value: str
    snippet: str
    source_url: str
    found_in_source: bool


class VerificationCheckOut(BaseModel):
    name: str
    passed: bool
    detail: str


class VerificationRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    checks: list[dict]
    requires_human_review: bool
    notes: str
    created_at: dt.datetime


class AdminOpportunityDetailOut(PublicOpportunityOut):
    external_key: str
    agent_id: str
    source_id: str
    confidence: str
    confidence_reasons: list[str]
    verification_status: str
    first_discovered_at: dt.datetime
    last_checked_at: dt.datetime | None
    last_updated_at: dt.datetime
    raw_title: str
    raw_text: str
    evidence: list[EvidenceOut]
    verification_records: list[VerificationRecordOut] = Field(default_factory=list)


class AdminOpportunityReviewRequest(BaseModel):
    action: str = Field(description="approve | reject | publish | unpublish | mark_expired")
    reason: str = Field(default="")
    title: str | None = None
    description: str | None = None
    eligibility: str | None = None
    deadline: dt.date | None = None


class ScanRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_id: str
    agent_id: str
    trigger: str
    status: str
    started_at: dt.datetime | None
    finished_at: dt.datetime | None
    duration_seconds: float | None
    items_seen: int
    items_new: int
    items_updated: int
    items_unchanged: int
    duplicates_detected: int
    items_skipped: int
    error: str | None
    log: list[dict]


class SourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    domain: str
    url: str
    agent_id: str
    parser: str
    categories: list[str]
    geographic_coverage: list[str]
    industry_relevance: list[str]
    collection_method: str
    reliability: str
    support_status: str
    issuing_organisation: str
    scan_frequency_minutes: int
    active: bool
    last_scan_at: dt.datetime | None
    last_success_at: dt.datetime | None
    last_failure_at: dt.datetime | None
    consecutive_failures: int


class SystemMetricsOut(BaseModel):
    total_sources: int
    active_sources: int
    supported_sources: int
    unsupported_sources: int
    total_scans: int
    successful_scans: int
    failed_scans: int
    total_opportunities: int
    published_opportunities: int
    pending_review_opportunities: int
    expired_opportunities: int
    duplicates_merged: int
