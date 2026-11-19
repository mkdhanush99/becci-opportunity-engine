"""Controlled vocabularies used across the system."""
from enum import StrEnum


class Category(StrEnum):
    JOB = "job"
    FUNDING = "funding"
    TENDER = "tender"
    LEARNING = "learning"
    EVENT = "event"
    BUSINESS_GROWTH = "business_growth"


class SourceReliability(StrEnum):
    OFFICIAL_GOVERNMENT = "official_government"
    OFFICIAL_EMPLOYER = "official_employer"
    RECOGNISED_INSTITUTION = "recognised_institution"
    THIRD_PARTY = "third_party"


class CollectionMethod(StrEnum):
    RSS = "rss"
    SITEMAP = "sitemap"
    DOCUMENT = "document"
    SEARCH_INTERFACE = "search_interface"
    BROWSER = "browser"
    HTTP_HTML = "http_html"
    DATA_FEED = "data_feed"


class SourceSupport(StrEnum):
    """Whether automated collection has been tested and is permitted."""
    UNTESTED = "untested"
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"  # blocked / disallowed / requires login / captcha


class LifecycleStatus(StrEnum):
    DISCOVERED = "discovered"
    EXTRACTED = "extracted"
    AWAITING_VERIFICATION = "awaiting_verification"
    NEEDS_HUMAN_REVIEW = "needs_human_review"
    APPROVED = "approved"
    PUBLISHED = "published"
    UPDATED = "updated"
    CLOSING_SOON = "closing_soon"
    EXPIRED = "expired"
    WITHDRAWN = "withdrawn"
    REJECTED = "rejected"


PUBLIC_STATUSES = {LifecycleStatus.PUBLISHED, LifecycleStatus.UPDATED, LifecycleStatus.CLOSING_SOON}


class VerificationStatus(StrEnum):
    PENDING = "pending"
    OFFICIAL_CONFIRMED = "official_confirmed"
    OFFICIAL_UNVERIFIED_DETAILS = "official_found_details_not_fully_verified"
    THIRD_PARTY = "third_party_source"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    EXPIRED = "expired"
    REMOVED = "removed"  # source no longer lists it (needs re-verification before withdrawal)
    CONFLICTING = "conflicting_information"
    SOURCE_UNREACHABLE = "source_unreachable"


class ExpiryStatus(StrEnum):
    ACTIVE = "active"
    CLOSING_SOON = "closing_soon"
    EXPIRED = "expired"
    DATE_UNAVAILABLE = "date_unavailable"


class ScanStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    BLOCKED = "blocked"  # robots/403/captcha/login: we stop, never bypass
    TIMEOUT = "timeout"


class AdminRole(StrEnum):
    VIEWER = "viewer"
    REVIEWER = "reviewer"
    ADMIN = "admin"


ROLE_RANK = {AdminRole.VIEWER: 0, AdminRole.REVIEWER: 1, AdminRole.ADMIN: 2}


class BECCISector(StrEnum):
    MANUFACTURING = "Manufacturing"
    TRADING_DISTRIBUTION = "Trading and distribution"
    SERVICES = "Services"
    HEALTHCARE = "Healthcare"
    EDUCATION_TRAINING = "Education and training"
    AGRICULTURE_ALLIED = "Agriculture and allied activities"
    IT_TECHNOLOGY = "IT and technology"
    CONSTRUCTION_INFRASTRUCTURE = "Construction and infrastructure"
    FINANCE_PROFESSIONAL = "Finance and professional services"
    HOSPITALITY_TOURISM = "Hospitality and tourism"
    OTHER = "Other industries"


class GeographicLevel(StrEnum):
    NATIONAL = "national"
    STATE = "state"
    DISTRICT = "district"
    LOCAL = "local"


class TenderStatus(StrEnum):
    UPCOMING = "upcoming"
    OPEN = "open"
    CLOSING_SOON = "closing_soon"
    CLOSED = "closed"
    CANCELLED = "cancelled"
    EXTENDED = "extended"
    UNDER_VERIFICATION = "under_verification"
    EXPIRED = "expired"


class BusinessType(StrEnum):
    MANUFACTURER = "manufacturer"
    TRADER_DISTRIBUTOR = "trader_distributor"
    SERVICE_PROVIDER = "service_provider"
    CONTRACTOR = "contractor"
    STARTUP = "startup"
    INDIVIDUAL_ENTREPRENEUR = "individual_entrepreneur"
    COOPERATIVE_SHG = "cooperative_shg"
    NGO_SOCIAL_ENTERPRISE = "ngo_social_enterprise"
    OTHER = "other"


class BusinessStage(StrEnum):
    IDEA_PRE_REVENUE = "idea_pre_revenue"
    EARLY_STAGE = "early_stage"
    MICRO = "micro"
    SMALL = "small"
    MEDIUM = "medium"
    ESTABLISHED = "established"


class RegistrationStatus(StrEnum):
    REGISTERED = "registered"
    APPLIED = "applied"
    NOT_REGISTERED = "not_registered"
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"


class GSTStatus(StrEnum):
    REGISTERED = "registered"
    EXEMPT = "exempt"
    NOT_REGISTERED = "not_registered"
    UNKNOWN = "unknown"


class EntityType(StrEnum):
    UNREGISTERED_INDIVIDUAL = "unregistered_individual"
    SOLE_PROPRIETORSHIP = "sole_proprietorship"
    PARTNERSHIP = "partnership"
    LLP = "llp"
    PRIVATE_LIMITED = "private_limited"
    PUBLIC_LIMITED = "public_limited"
    OPC = "opc"
    SOCIETY_TRUST_COOPERATIVE = "society_trust_cooperative"
    OTHER = "other"


class EligibilityMatchStatus(StrEnum):
    LIKELY_MATCH = "likely_match"
    PARTIAL_MATCH = "partial_match"
    NOT_ELIGIBLE = "not_eligible"
    INSUFFICIENT_INFORMATION = "insufficient_information"
    REQUIRES_MANUAL_REVIEW = "requires_manual_review"


class MatchFeedbackType(StrEnum):
    FALSE_POSITIVE = "false_positive"
    CONFIRMED_GOOD = "confirmed_good"
    INCOMPLETE_ELIGIBILITY = "incomplete_eligibility"


# --------------------------------------------------------------------------- Government Schemes Controlled Vocabularies
class BeneficiaryClassification(StrEnum):
    OBC_BC_SPECIFIC = "obc_bc_specific"
    GENERAL_MSME = "general_msme"
    WOMEN_ENTREPRENEURS = "women_entrepreneurs"
    STUDENTS = "students"
    ARTISANS = "artisans"
    FARMERS = "farmers"
    GENERAL_ENTREPRENEURSHIP = "general_entrepreneurship"
    OTHER_ELIGIBLE = "other_eligible"


class GeographicalScope(StrEnum):
    PAN_INDIA = "pan_india"
    TELANGANA = "telangana"
    ANDHRA_PRADESH = "andhra_pradesh"


class SourceVerificationStatus(StrEnum):
    VERIFIED = "verified"
    PARTIALLY_VERIFIED = "partially_verified"
    UNVERIFIED = "unverified"


class SchemeApplicationStatus(StrEnum):
    OPEN = "open"
    UPCOMING = "upcoming"
    CLOSED = "closed"
    CONTINUOUS = "continuous"
    SUSPENDED = "suspended"
    UNKNOWN = "unknown"


class BenefitType(StrEnum):
    GRANT = "grant"
    SUBSIDY = "subsidy"
    LOAN = "loan"
    SCHOLARSHIP = "scholarship"
    REIMBURSEMENT = "reimbursement"
    TRAINING = "training"
    OTHER = "other"


class SchemeEligibilityAssessmentStatus(StrEnum):
    ELIGIBLE = "eligible"
    POTENTIALLY_ELIGIBLE = "potentially_eligible"
    NOT_ELIGIBLE = "not_eligible"
    CANNOT_ESTABLISH = "cannot_establish"



