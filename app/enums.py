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

