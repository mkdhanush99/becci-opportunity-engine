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
class TenderDetailOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tender_id: str | None
    reference_number: str | None
    issuing_authority: str
    department: str
    tender_category: str
    product_category: str
    sector: str
    estimated_value: str
    emd_amount: str
    tender_fee: str
    document_download_date: dt.date | None
    pre_bid_date: dt.date | None
    pre_bid_details: str
    bid_opening_date: dt.date | None
    turnover_requirement: str
    experience_requirement: str
    required_registrations: list[str] = Field(default_factory=list)
    msme_preference: str
    eligibility_intelligence: dict = Field(default_factory=dict)
    tender_status: str
    corrigendum_history: list[dict] = Field(default_factory=list)
    cancellation_reason: str | None


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
    tender_detail: TenderDetailOut | None = None
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
    access_notes: str = ""
    issuing_organisation: str
    scan_frequency_minutes: int
    active: bool
    last_scan_at: dt.datetime | None
    last_success_at: dt.datetime | None
    last_failure_at: dt.datetime | None
    last_failure_reason: str | None = None
    consecutive_failures: int
    next_scan_at: dt.datetime | None = None



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


# --------------------------------------------------------------------------- Phase 3: Member, Profile & Matching Schemas
class MemberRegisterRequest(BaseModel):
    email: str = Field(min_length=5, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=2, max_length=128)


class MemberLoginRequest(BaseModel):
    email: str
    password: str


class MemberTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    member_id: str
    email: str
    display_name: str


class BusinessProfileIn(BaseModel):
    business_name: str = Field(min_length=2, max_length=255)
    business_type: str = Field(description="manufacturer | trader_distributor | service_provider | contractor | startup | individual_entrepreneur | cooperative_shg | ngo_social_enterprise | other")
    industry: str | None = Field(default=None, max_length=128)
    becci_sector: str = Field(description="One of the 11 BECCI sectors")
    secondary_sectors: list[str] = Field(default_factory=list, max_length=5)
    state: str = Field(min_length=2, max_length=64)
    district: str | None = Field(default=None, max_length=128)
    business_stage: str = Field(default="micro")
    msme_udyam_status: str = Field(default="unknown", description="registered | applied | not_registered | not_applicable | unknown")
    gst_status: str = Field(default="unknown", description="registered | exempt | not_registered | unknown")
    entity_type: str = Field(default="sole_proprietorship")
    annual_turnover_lakhs: float | None = Field(default=None, ge=0.0)
    years_of_experience: float | None = Field(default=None, ge=0.0)
    licences_and_registrations: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    products_and_services: list[str] = Field(default_factory=list)
    preferred_categories: list[str] = Field(default_factory=lambda: ["tender", "funding", "job"])


class BusinessProfileOut(BusinessProfileIn):
    model_config = ConfigDict(from_attributes=True)

    id: str
    member_id: str
    created_at: dt.datetime
    updated_at: dt.datetime


class EligibilityExplanationOut(BaseModel):
    eligibility_status: str
    why_it_matches: list[str]
    satisfied_conditions: list[str]
    missing_requirements: list[str]
    details_to_confirm: list[str]
    required_documents: list[str]
    disclaimer: str


class OpportunityMatchOut(BaseModel):
    opportunity: PublicOpportunityOut
    relevance_score: float
    is_active_recommendation: bool
    eligibility: EligibilityExplanationOut
    score_breakdown: dict[str, dict]
    ranking_reasons: list[str]
    is_saved: bool = False
    is_viewed: bool = False


class RecommendationListResponse(BaseModel):
    profile_id: str
    business_name: str
    items: list[OpportunityMatchOut]
    total: int
    page: int
    limit: int
    has_more: bool


class SaveOpportunityRequest(BaseModel):
    notes: str | None = Field(default=None, max_length=1000)


class SavedOpportunityOut(BaseModel):
    opportunity_id: str
    notes: str | None
    saved_at: dt.datetime
    opportunity: PublicOpportunityOut


class ViewedOpportunityOut(BaseModel):
    opportunity_id: str
    view_count: int
    first_viewed_at: dt.datetime
    last_viewed_at: dt.datetime
    opportunity: PublicOpportunityOut


class MatchingConfigOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    sector_weight: float
    geography_weight: float
    eligibility_weight: float
    deadline_urgency_weight: float
    category_preference_weight: float
    verification_weight: float
    min_score_threshold: float
    exclude_expired: bool
    updated_by: str
    updated_at: dt.datetime


class MatchingConfigUpdate(BaseModel):
    sector_weight: float | None = Field(default=None, ge=0.0, le=100.0)
    geography_weight: float | None = Field(default=None, ge=0.0, le=100.0)
    eligibility_weight: float | None = Field(default=None, ge=0.0, le=100.0)
    deadline_urgency_weight: float | None = Field(default=None, ge=0.0, le=100.0)
    category_preference_weight: float | None = Field(default=None, ge=0.0, le=100.0)
    verification_weight: float | None = Field(default=None, ge=0.0, le=100.0)
    min_score_threshold: float | None = Field(default=None, ge=0.0, le=100.0)
    exclude_expired: bool | None = None


class MatchFeedbackIn(BaseModel):
    business_profile_id: str
    opportunity_id: str
    flag_type: str = Field(description="false_positive | confirmed_good | incomplete_eligibility")
    reason: str = Field(min_length=3, max_length=1000)


class MatchFeedbackOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    business_profile_id: str
    opportunity_id: str
    flag_type: str
    reason: str
    actor: str
    created_at: dt.datetime


class IncompleteEligibilityOut(BaseModel):
    opportunity: PublicOpportunityOut
    incomplete_reasons: list[str]

