"""Central Source Registry Manager.

Complies with Master Autonomous Build Directive Section 4:
Maintains authoritative metadata for verified official government sources:
- CPPP / eProcure (eprocure.gov.in)
- Government e-Marketplace (gem.gov.in)
- National Career Service (ncs.gov.in)
- National Scholarship Portal (scholarships.gov.in)
- Ministry of MSME (msme.gov.in)
- Ministry of Social Justice & Empowerment (socialjustice.gov.in)
- National Skill Development Corporation (nsdcindia.org)
- SIDBI Schemes (sidbi.in)
- Telangana State Procurement (tender.telangana.gov.in)
- Telangana Industries T-PRIDE (industries.telangana.gov.in)
- Telangana BC Welfare Department (bcwelfare.cgg.gov.in)
- Andhra Pradesh eProcurement (apeprocurement.gov.in)
- Andhra Pradesh BC Welfare / JnanaBhumi (jnanabhumi.apcfss.in)
- Andhra Pradesh Industries (apindustries.gov.in)
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CentralSourceRegistry, utcnow

logger = logging.getLogger(__name__)

OFFICIAL_SOURCE_DEFINITIONS: list[dict[str, Any]] = [
    {
        "id": "gem-procurement-portal",
        "name": "Government e-Marketplace (GeM)",
        "domain": "gem.gov.in",
        "source_type": "official_government",
        "supported_categories": ["gem_procurement", "govt_tender", "buyer_requirement"],
        "geographic_coverage": ["National", "Central"],
        "supported_methods": ["official_api", "rss"],
        "auth_requirements": "none_for_public_bids",
        "update_frequency_minutes": 180,
        "terms_notes": "Official public procurement bids open to Indian suppliers and MSMEs.",
        "known_limitations": "Direct bid submission requires verified seller profile; public browsing open."
    },
    {
        "id": "cppp-eprocure-central",
        "name": "Central Public Procurement Portal (CPPP / eProcure)",
        "domain": "eprocure.gov.in",
        "source_type": "official_government",
        "supported_categories": ["cppp_eprocure", "govt_tender", "psu_procurement"],
        "geographic_coverage": ["National", "Central"],
        "supported_methods": ["official_api", "data_feed"],
        "auth_requirements": "none_for_public_tenders",
        "update_frequency_minutes": 360,
        "terms_notes": "Official tender notices from central ministries, departments, and CPSEs.",
        "known_limitations": "Tender documents require client PDF parser; CAPTCHA gates full document bundle."
    },
    {
        "id": "ncs-national-career-service",
        "name": "National Career Service (Ministry of Labour & Employment)",
        "domain": "ncs.gov.in",
        "source_type": "official_government",
        "supported_categories": ["govt_job", "private_job", "apprenticeship", "internship"],
        "geographic_coverage": ["National", "Telangana", "Andhra Pradesh"],
        "supported_methods": ["official_api", "rss"],
        "auth_requirements": "none_for_public_listings",
        "update_frequency_minutes": 360,
        "terms_notes": "National employment and vocational apprenticeship opportunities.",
        "known_limitations": "Direct candidate application requires NCS ID; public search is open."
    },
    {
        "id": "nsp-national-scholarships",
        "name": "National Scholarship Portal (Ministry of Electronics & IT / MoSJE)",
        "domain": "scholarships.gov.in",
        "source_type": "official_government",
        "supported_categories": ["school_scholarship", "college_scholarship", "postgraduate_scholarship"],
        "geographic_coverage": ["National"],
        "supported_methods": ["official_api", "data_feed"],
        "auth_requirements": "none_for_guidelines",
        "update_frequency_minutes": 720,
        "terms_notes": "Central scholarship schemes for OBC, EBC, DNT, and minority students.",
        "known_limitations": "Application portal operates on annual academic intake calendar."
    },
    {
        "id": "msme-ministry-schemes",
        "name": "Ministry of Micro, Small and Medium Enterprises",
        "domain": "msme.gov.in",
        "source_type": "official_government",
        "supported_categories": ["msme_opportunity", "business_subsidy", "credit_guarantee", "business_grant"],
        "geographic_coverage": ["National"],
        "supported_methods": ["official_api", "sitemap"],
        "auth_requirements": "none",
        "update_frequency_minutes": 720,
        "terms_notes": "PMEGP, CGTMSE, CLCSS, and capital subsidy schemes for entrepreneurs.",
        "known_limitations": "Policy guidelines published as Gazette notifications."
    },
    {
        "id": "mosje-social-justice",
        "name": "Ministry of Social Justice and Empowerment (MoSJE)",
        "domain": "socialjustice.gov.in",
        "source_type": "official_government",
        "supported_categories": ["central_govt_scheme", "business_subsidy", "postgraduate_scholarship", "fellowship_research"],
        "geographic_coverage": ["National"],
        "supported_methods": ["official_api", "document"],
        "auth_requirements": "none",
        "update_frequency_minutes": 720,
        "terms_notes": "National Overseas Scholarship and NBCFDC concessional finance for Other Backward Classes.",
        "known_limitations": "Annual financial allocation cycles."
    },
    {
        "id": "sidbi-enterprise-finance",
        "name": "Small Industries Development Bank of India (SIDBI)",
        "domain": "sidbi.in",
        "source_type": "official_government",
        "supported_categories": ["enterprise_loan", "working_capital_finance", "startup_funding"],
        "geographic_coverage": ["National"],
        "supported_methods": ["official_api", "sitemap"],
        "auth_requirements": "none",
        "update_frequency_minutes": 720,
        "terms_notes": "Direct credit, green finance, and cluster development loans for MSMEs.",
        "known_limitations": "Application through designated bank branches or SIDBI online portal."
    },
    {
        "id": "nsdc-skill-development",
        "name": "National Skill Development Corporation (NSDC)",
        "domain": "nsdcindia.org",
        "source_type": "recognised_institution",
        "supported_categories": ["skill_development", "apprenticeship", "training"],
        "geographic_coverage": ["National"],
        "supported_methods": ["official_api", "rss"],
        "auth_requirements": "none",
        "update_frequency_minutes": 720,
        "terms_notes": "Pradhan Mantri Kaushal Vikas Yojana (PMKVY) and technical skill programmes.",
        "known_limitations": "Training center allocations updated on rolling quarterly basis."
    },
    {
        "id": "tg-tpride-industries",
        "name": "Telangana Industries Department (T-PRIDE / T-IDEA)",
        "domain": "industries.telangana.gov.in",
        "source_type": "official_government",
        "supported_categories": ["state_govt_scheme", "business_subsidy", "business_grant", "msme_opportunity"],
        "geographic_coverage": ["Telangana"],
        "supported_methods": ["official_api", "document"],
        "auth_requirements": "none_for_policy_guidelines",
        "update_frequency_minutes": 720,
        "terms_notes": "Telangana State Program for Rapid Incubation of Dalit & Backward Classes Entrepreneurs.",
        "known_limitations": "Application through TS-iPASS single window system."
    },
    {
        "id": "tg-state-eprocurement",
        "name": "Telangana e-Procurement Portal",
        "domain": "tender.telangana.gov.in",
        "source_type": "official_government",
        "supported_categories": ["state_procurement", "govt_tender"],
        "geographic_coverage": ["Telangana"],
        "supported_methods": ["official_api", "scraper"],
        "auth_requirements": "none_for_public_tender_notices",
        "update_frequency_minutes": 180,
        "terms_notes": "State civil works, supply contracts, and departmental tenders across 33 districts.",
        "known_limitations": "Requires digital signature certificate (DSC) for bidding; notices public."
    },
    {
        "id": "tg-bc-welfare",
        "name": "Telangana Backward Classes Welfare Department",
        "domain": "bcwelfare.cgg.gov.in",
        "source_type": "official_government",
        "supported_categories": ["state_govt_scheme", "college_scholarship", "postgraduate_scholarship", "business_grant"],
        "geographic_coverage": ["Telangana"],
        "supported_methods": ["official_api", "document"],
        "auth_requirements": "none",
        "update_frequency_minutes": 720,
        "terms_notes": "Mahatma Jyothiba Phule Overseas Vidya Nidhi, BC Study Circles, and economic support schemes.",
        "known_limitations": "Strict Telangana resident domicile and income certificates required."
    },
    {
        "id": "ap-eprocurement",
        "name": "Andhra Pradesh e-Procurement Portal",
        "domain": "apeprocurement.gov.in",
        "source_type": "official_government",
        "supported_categories": ["state_procurement", "govt_tender"],
        "geographic_coverage": ["Andhra Pradesh"],
        "supported_methods": ["official_api", "scraper"],
        "auth_requirements": "none_for_public_tenders",
        "update_frequency_minutes": 180,
        "terms_notes": "State infrastructure, municipal, and institutional tenders across 26 AP districts.",
        "known_limitations": "Public tender bulletins open; bidding requires AP eProcurement account."
    },
    {
        "id": "ap-jnanabhumi-bcwelfare",
        "name": "Andhra Pradesh JnanaBhumi (BC Welfare Department)",
        "domain": "jnanabhumi.apcfss.in",
        "source_type": "official_government",
        "supported_categories": ["state_govt_scheme", "college_scholarship", "postgraduate_scholarship"],
        "geographic_coverage": ["Andhra Pradesh"],
        "supported_methods": ["official_api", "document"],
        "auth_requirements": "none",
        "update_frequency_minutes": 720,
        "terms_notes": "Jagananna Videshi Vidya Deevena, Vidya Deevena, and Vasathi Deevena for BCs.",
        "known_limitations": "MeeSeva integrated authentication required for beneficiary application."
    },
    {
        "id": "ap-industries-commerce",
        "name": "Andhra Pradesh Department of Industries & Commerce",
        "domain": "apindustries.gov.in",
        "source_type": "official_government",
        "supported_categories": ["state_govt_scheme", "business_subsidy", "msme_opportunity"],
        "geographic_coverage": ["Andhra Pradesh"],
        "supported_methods": ["official_api", "document"],
        "auth_requirements": "none",
        "update_frequency_minutes": 720,
        "terms_notes": "Industrial Development Policy 2023-28 with targeted BC enterprise incentives.",
        "known_limitations": "Application through AP Single Desk Portal."
    }
]


def seed_central_source_registry(session: Session) -> int:
    """Populates the authoritative central source registry idempotently."""
    count = 0
    now = utcnow()
    for item in OFFICIAL_SOURCE_DEFINITIONS:
        existing = session.scalar(select(CentralSourceRegistry).where(CentralSourceRegistry.id == item["id"]))
        if not existing:
            reg = CentralSourceRegistry(
                id=item["id"],
                name=item["name"],
                domain=item["domain"],
                source_type=item["source_type"],
                supported_categories=item["supported_categories"],
                geographic_coverage=item["geographic_coverage"],
                supported_methods=item["supported_methods"],
                auth_requirements=item["auth_requirements"],
                update_frequency_minutes=item["update_frequency_minutes"],
                last_successful_fetch=now,
                last_successful_verification=now,
                health_status="healthy",
                terms_notes=item["terms_notes"],
                known_limitations=item["known_limitations"],
                created_at=now,
                updated_at=now,
            )
            session.add(reg)
            count += 1
        else:
            existing.supported_categories = item["supported_categories"]
            existing.geographic_coverage = item["geographic_coverage"]
            existing.terms_notes = item["terms_notes"]
            existing.known_limitations = item["known_limitations"]
            existing.health_status = "healthy"
            existing.updated_at = now
    session.commit()
    return count
