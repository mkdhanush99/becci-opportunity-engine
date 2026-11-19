"""Comprehensive Phase 3 test suite: Business Profiles, Opportunity Matching, Eligibility Intelligence,
Ranking Consistency, Member Isolation, API Authentication & Admin Matching Controls.
"""
from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path
from fastapi.testclient import TestClient

from app.db import get_engine, session_scope
from app.enums import (
    BECCISector,
    EligibilityMatchStatus,
    ExpiryStatus,
    LifecycleStatus,
    TenderStatus,
    VerificationStatus,
)
from app.main import app
from app.matching.engine import ELIGIBILITY_DISCLAIMER, evaluate_match, rank_opportunities_for_profile
from app.migrations import list_applied_migrations
from app.models import BusinessProfile, MatchingConfig, Opportunity, TenderDetail, new_id, utcnow

client = TestClient(app)


def _seed_test_opportunities(session) -> dict[str, str]:
    """Creates a realistic set of opportunities in the isolated test DB for matching tests."""
    now = utcnow()
    today = dt.date.today()
    ids: dict[str, str] = {}

    def add_opp(
        *,
        key: str,
        title: str,
        category: str,
        sector: str,
        state: str | None,
        city: str | None = None,
        deadline_offset: int | None = 15,
        lifecycle: str = LifecycleStatus.PUBLISHED,
        verification: str = VerificationStatus.OFFICIAL_CONFIRMED,
        subcategory: str | None = None,
        tender_kwargs: dict | None = None,
        eligibility_text: str = "Refer to official notice",
    ) -> str:
        oid = new_id()
        dl = (today + dt.timedelta(days=deadline_offset)) if deadline_offset is not None else None
        exp = (
            ExpiryStatus.EXPIRED
            if (dl and dl < today)
            else (ExpiryStatus.CLOSING_SOON if (dl and (dl - today).days <= 7) else (ExpiryStatus.ACTIVE if dl else ExpiryStatus.DATE_UNAVAILABLE))
        )
        opp = Opportunity(
            id=oid,
            external_key=f"p3test:{key}:{oid[:6]}",
            slug=f"p3-{key}-{oid[:8]}",
            title=title,
            description=title,
            category=category,
            subcategory=subcategory,
            issuing_organisation="Official Government Authority",
            publisher="Test Portal",
            source_type="official_government",
            source_name="Test Portal",
            country="India",
            state=state,
            city=city,
            location_type="local" if city else ("state" if state else "national"),
            industry=sector,
            eligibility=eligibility_text,
            deadline=dl,
            original_url="https://eprocure.gov.in/eprocure/app",
            lifecycle_status=lifecycle,
            verification_status=verification,
            expiry_status=exp,
            agent_id="tender_scout" if category == "tender" else "funding_scout",
            source_id="cppp-eprocure" if category == "tender" else "sidbi-schemes",
            content_fingerprint=oid,
            title_fingerprint=oid,
            raw_title=title,
            raw_text=title,
            raw_fields={},
            is_fixture=False,
            extracted_at=now,
            verified_at=now if verification == VerificationStatus.OFFICIAL_CONFIRMED else None,
        )
        if tender_kwargs is not None:
            opp.tender_detail = TenderDetail(
                opportunity_id=oid,
                tender_id=f"T-{key}",
                reference_number=f"REF-{key}",
                issuing_authority="Official Government Authority",
                department="Procurement Wing",
                tender_category=tender_kwargs.get("tender_category", "Goods"),
                product_category=tender_kwargs.get("product_category", title),
                sector=sector,
                turnover_requirement=tender_kwargs.get("turnover_requirement", "Not stated"),
                experience_requirement=tender_kwargs.get("experience_requirement", "Not stated"),
                required_registrations=tender_kwargs.get("required_registrations", []),
                msme_preference=tender_kwargs.get("msme_preference", "Not stated"),
                eligibility_intelligence=tender_kwargs.get("eligibility_intelligence", {}),
                tender_status=tender_kwargs.get("tender_status", TenderStatus.OPEN.value),
                updated_at=now,
            )
        session.add(opp)
        ids[key] = oid
        return oid

    # 1. Strong IT Tender in Telangana (Hyderabad), closing soon, MSE relaxation + GST + 10L turnover + 2 yr exp
    add_opp(
        key="it_telangana_open",
        title="Supply of High-End Laptops and Cybersecurity Software Solutions in Hyderabad",
        category="tender",
        sector=BECCISector.IT_TECHNOLOGY.value,
        state="Telangana",
        city="Hyderabad",
        deadline_offset=5,
        tender_kwargs={
            "tender_category": "Goods",
            "product_category": "High-End Laptops and Cybersecurity Software",
            "turnover_requirement": "10 Lakh (s)",
            "experience_requirement": "2 Year (s)",
            "required_registrations": ["GST Registration", "Udyam Registration (for MSE benefits)"],
            "msme_preference": "MSE Relaxation (Experience & Turnover): Yes | Complete; MSE Purchase Preference",
            "eligibility_intelligence": {
                "gst_requirement": "Valid GSTIN required",
                "bidder_turnover_conditions": "10 Lakh (s)",
                "turnover_field_variant": "bidder_average_annual_turnover",
                "ambiguous_flag": False,
            },
        },
    )

    # 2. OEM-only Manufacturing Tender in Maharashtra (excludes traders)
    add_opp(
        key="mfg_oem_only",
        title="Supply of Industrial LED Luminaires and Solar Power Equipment in Pune",
        category="tender",
        sector=BECCISector.MANUFACTURING.value,
        state="Maharashtra",
        city="Pune",
        deadline_offset=18,
        tender_kwargs={
            "tender_category": "Goods",
            "product_category": "Industrial LED Luminaires",
            "turnover_requirement": "OEM Average Turnover (Last 3 Years): 20 Lakh (s)",
            "experience_requirement": "3 Year (s)",
            "required_registrations": ["GST Registration", "Manufacturer / OEM Authorization"],
            "eligibility_intelligence": {
                "gst_requirement": "GSTIN required",
                "company_registration": "The bidder must be the manufacturer / OEM. Traders are excluded.",
                "oem_turnover_conditions": "20 Lakh (s)",
                "turnover_field_variant": "oem_average_turnover_3yr",
                "ambiguous_flag": False,
            },
        },
    )

    # 3. Construction Tender in Maharashtra (for wrong-sector & state tests)
    add_opp(
        key="civil_maharashtra",
        title="Special Repairs of Highway Slope Protection Civil Works in Maharashtra",
        category="tender",
        sector=BECCISector.CONSTRUCTION_INFRASTRUCTURE.value,
        state="Maharashtra",
        city="Mumbai",
        deadline_offset=20,
        tender_kwargs={
            "tender_category": "Works",
            "product_category": "Civil Works",
            "turnover_requirement": "50 Lakh (s)",
            "experience_requirement": "5 Year (s)",
            "required_registrations": ["GST Registration", "PAN"],
            "eligibility_intelligence": {
                "gst_requirement": "GST required",
                "bidder_turnover_conditions": "50 Lakh (s)",
                "ambiguous_flag": False,
            },
        },
    )

    # 4. National Innovation Challenge Funding (for startups / early-stage)
    add_opp(
        key="innovation_funding",
        title="SIDBI Innovation Challenge Fund 2nd Cohort Applications Open",
        category="funding",
        subcategory="innovation_challenge",
        sector=BECCISector.SERVICES.value,
        state=None,
        deadline_offset=12,
        eligibility_text="Open to Indian startups and MSME innovators",
    )

    # 5. National Vendor Empanelment
    add_opp(
        key="empanelment_national",
        title="Empanelment of IT and Digital Implementation Agencies Nationwide",
        category="tender",
        subcategory="empanelment",
        sector=BECCISector.IT_TECHNOLOGY.value,
        state=None,
        deadline_offset=25,
        tender_kwargs={
            "tender_category": "Empanelment",
            "product_category": "IT Implementation Agencies",
            "eligibility_intelligence": {"ambiguous_flag": True},
        },
    )

    # 6. Government Job notice (Telangana)
    add_opp(
        key="govt_job_tg",
        title="TGPSC Recruitment for Technical Officers",
        category="job",
        sector=BECCISector.IT_TECHNOLOGY.value,
        state="Telangana",
        deadline_offset=14,
        eligibility_text="Bachelor's degree in relevant discipline",
    )

    # 7. EXPIRED IT Tender (must NEVER appear as high-priority active recommendation)
    add_opp(
        key="expired_it_tender",
        title="Expired Procurement of High-End Laptops in Hyderabad",
        category="tender",
        sector=BECCISector.IT_TECHNOLOGY.value,
        state="Telangana",
        city="Hyderabad",
        deadline_offset=-5,
        tender_kwargs={
            "tender_category": "Goods",
            "tender_status": TenderStatus.EXPIRED.value,
            "eligibility_intelligence": {"ambiguous_flag": False},
        },
    )

    # 8. UNVERIFIED & UNPUBLISHED IT Tender (must NEVER bypass publication workflow)
    add_opp(
        key="unverified_it_tender",
        title="Unverified Cloud Server Procurement in Hyderabad",
        category="tender",
        sector=BECCISector.IT_TECHNOLOGY.value,
        state="Telangana",
        city="Hyderabad",
        deadline_offset=10,
        lifecycle=LifecycleStatus.NEEDS_HUMAN_REVIEW,
        verification=VerificationStatus.INSUFFICIENT_EVIDENCE,
        tender_kwargs={
            "tender_category": "Goods",
            "tender_status": TenderStatus.UNDER_VERIFICATION.value,
            "eligibility_intelligence": {"ambiguous_flag": True},
        },
    )

    session.commit()
    return ids


def _register_and_login(email: str, password: str = "BecciMember2026!", name: str = "Test Member") -> dict:
    r = client.post("/api/v1/member/auth/register", json={"email": email, "password": password, "display_name": name})
    assert r.status_code == 201, r.text
    return r.json()


def _admin_headers() -> dict:
    r = client.post("/api/admin/auth/login", json={"username": "admin", "password": "BecciAdmin2026!"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_phase3_migration_and_matching_engine_rules():
    # Confirm migration 003 applied
    versions = [m["version"] for m in list_applied_migrations(get_engine())]
    assert "003_phase3_business_profiles_and_matching" in versions

    with session_scope() as session:
        ids = _seed_test_opportunities(session)
        cfg = MatchingConfig(id="test_cfg")

        # Profile 1: Registered IT MSME in Hyderabad, Telangana (strong match for IT Telangana tender)
        p_it_msme = BusinessProfile(
            id=new_id(),
            member_id="m1",
            business_name="Deccan Tech Solutions",
            business_type="service_provider",
            industry="IT & Cybersecurity",
            becci_sector=BECCISector.IT_TECHNOLOGY.value,
            secondary_sectors=[],
            state="Telangana",
            district="Hyderabad",
            business_stage="small",
            msme_udyam_status="registered",
            gst_status="registered",
            entity_type="private_limited",
            annual_turnover_lakhs=25.0,
            years_of_experience=4.0,
            licences_and_registrations=["PAN", "ISO 9001"],
            capabilities=["cybersecurity", "cloud"],
            products_and_services=["laptops", "software"],
            preferred_categories=["tender", "funding"],
        )

        # 1. Exact sector + district + satisfied eligibility -> likely_match, high score
        ev_it = evaluate_match(p_it_msme, session.get(Opportunity, ids["it_telangana_open"]), cfg)
        assert ev_it.eligibility_status == EligibilityMatchStatus.LIKELY_MATCH.value
        assert ev_it.is_active_recommendation is True
        assert ev_it.relevance_score >= 85.0
        assert ev_it.disclaimer == ELIGIBILITY_DISCLAIMER
        assert len(ev_it.why_it_matches) >= 2
        assert len(ev_it.satisfied_conditions) >= 2
        assert "GST Registration" in ev_it.required_documents

        # 2. Wrong sector (Civil Works in Maharashtra) -> sector score 0, score capped <= 35, not_eligible due to turnover/exp
        ev_civil = evaluate_match(p_it_msme, session.get(Opportunity, ids["civil_maharashtra"]), cfg)
        assert ev_civil.score_breakdown["sector_and_capability"]["score"] == 0.0
        assert ev_civil.relevance_score <= 25.0
        assert ev_civil.eligibility_status == EligibilityMatchStatus.NOT_ELIGIBLE.value

        # 3. Expired tender -> score 0.0, not active recommendation, not_eligible
        ev_exp = evaluate_match(p_it_msme, session.get(Opportunity, ids["expired_it_tender"]), cfg)
        assert ev_exp.relevance_score == 0.0
        assert ev_exp.is_active_recommendation is False
        assert ev_exp.eligibility_status == EligibilityMatchStatus.NOT_ELIGIBLE.value

        # 4. Unverified / unpublished tender -> requires_manual_review, not active recommendation
        ev_unv = evaluate_match(p_it_msme, session.get(Opportunity, ids["unverified_it_tender"]), cfg)
        assert ev_unv.eligibility_status == EligibilityMatchStatus.REQUIRES_MANUAL_REVIEW.value
        assert ev_unv.is_active_recommendation is False

        # 5. Trader vs OEM-only tender -> hard disqualifier -> not_eligible
        p_trader = BusinessProfile(
            id=new_id(),
            member_id="m2",
            business_name="Pune Trading Co",
            business_type="trader_distributor",
            becci_sector=BECCISector.MANUFACTURING.value,
            secondary_sectors=[],
            state="Maharashtra",
            district="Pune",
            business_stage="micro",
            msme_udyam_status="not_registered",
            gst_status="registered",
            entity_type="sole_proprietorship",
            annual_turnover_lakhs=30.0,
            years_of_experience=5.0,
            licences_and_registrations=["PAN"],
            capabilities=["distribution"],
            products_and_services=["led luminaires"],
            preferred_categories=["tender"],
        )
        ev_trader = evaluate_match(p_trader, session.get(Opportunity, ids["mfg_oem_only"]), cfg)
        assert ev_trader.eligibility_status == EligibilityMatchStatus.NOT_ELIGIBLE.value
        assert any("OEM" in m or "trader" in m.lower() for m in ev_trader.missing_requirements)

        # 6. Missing registration & omitted turnover/experience -> NEVER assumes GST/Udyam, returns partial_match or insufficient_information
        p_informal = BusinessProfile(
            id=new_id(),
            member_id="m3",
            business_name="Emerging IT Micro Enterprise",
            business_type="startup",
            becci_sector=BECCISector.IT_TECHNOLOGY.value,
            secondary_sectors=[],
            state="Telangana",
            district="Warangal",
            business_stage="early_stage",
            msme_udyam_status="not_registered",
            gst_status="not_registered",
            entity_type="unregistered_individual",
            annual_turnover_lakhs=None,
            years_of_experience=None,
            licences_and_registrations=[],
            capabilities=["software"],
            products_and_services=["laptops"],
            preferred_categories=["tender", "funding"],
        )
        ev_inf = evaluate_match(p_informal, session.get(Opportunity, ids["it_telangana_open"]), cfg)
        assert ev_inf.eligibility_status == EligibilityMatchStatus.PARTIAL_MATCH.value
        assert any("GST" in m for m in ev_inf.missing_requirements)
        assert any("turnover" in c.lower() for c in ev_inf.details_to_confirm)
        assert any("experience" in c.lower() for c in ev_inf.details_to_confirm)

        # 7. Startup matches Innovation Challenge Funding
        ev_fund = evaluate_match(p_informal, session.get(Opportunity, ids["innovation_funding"]), cfg)
        assert ev_fund.eligibility_status in (
            EligibilityMatchStatus.LIKELY_MATCH.value,
            EligibilityMatchStatus.PARTIAL_MATCH.value,
        )
        assert ev_fund.is_active_recommendation is True

        # 8. Ranking consistency: repeated ranking yields identical order and excludes expired/unverified
        ranked1 = rank_opportunities_for_profile(session, p_it_msme)
        ranked2 = rank_opportunities_for_profile(session, p_it_msme)
        assert [r.opportunity.id for r in ranked1] == [r.opportunity.id for r in ranked2]
        returned_ids = {r.opportunity.id for r in ranked1}
        assert ids["it_telangana_open"] in returned_ids
        assert ids["expired_it_tender"] not in returned_ids
        assert ids["unverified_it_tender"] not in returned_ids
        # Strong IT Telangana tender ranks above general funding
        assert ranked1[0].opportunity.id == ids["it_telangana_open"]


def test_member_api_auth_isolation_and_saved_viewed_flow():
    with session_scope() as session:
        ids = _seed_test_opportunities(session)

    # Unauthenticated access rejected
    assert client.get("/api/v1/member/profile").status_code == 401
    assert client.get("/api/v1/member/recommendations").status_code == 401

    # Register two separate members
    m1 = _register_and_login("member_a@becci-test.in", name="Member A")
    m2 = _register_and_login("member_b@becci-test.in", name="Member B")
    h1 = {"Authorization": f"Bearer {m1['access_token']}"}
    h2 = {"Authorization": f"Bearer {m2['access_token']}"}
    h_admin = _admin_headers()

    # Cross-auth isolation: member token cannot access admin; admin token cannot access member
    assert client.get("/api/admin/matching/config", headers=h1).status_code == 401
    assert client.get("/api/v1/member/profile", headers=h_admin).status_code == 401

    # Member A creates IT Telangana profile
    prof_a = client.post(
        "/api/v1/member/profile",
        headers=h1,
        json={
            "business_name": "Telangana Digital Systems",
            "business_type": "service_provider",
            "industry": "Cybersecurity & IT",
            "becci_sector": "IT and technology",
            "state": "Telangana",
            "district": "Hyderabad",
            "business_stage": "small",
            "msme_udyam_status": "registered",
            "gst_status": "registered",
            "entity_type": "private_limited",
            "annual_turnover_lakhs": 20.0,
            "years_of_experience": 3.0,
            "licences_and_registrations": ["PAN", "GeM Seller"],
            "capabilities": ["cybersecurity", "laptops"],
            "products_and_services": ["M365", "laptops"],
            "preferred_categories": ["tender", "funding"],
        },
    )
    assert prof_a.status_code == 200
    assert prof_a.json()["business_name"] == "Telangana Digital Systems"

    # Member B has NOT created a profile -> gets 404 (cannot see Member A's profile)
    assert client.get("/api/v1/member/profile", headers=h2).status_code == 404

    # Member A gets personalised recommendations (no expired or unverified items)
    recs = client.get("/api/v1/member/recommendations", headers=h1)
    assert recs.status_code == 200
    data = recs.json()
    assert data["total"] >= 1
    rec_ids = [item["opportunity"]["id"] for item in data["items"]]
    assert ids["it_telangana_open"] in rec_ids
    assert ids["expired_it_tender"] not in rec_ids
    assert ids["unverified_it_tender"] not in rec_ids

    # Member A inspects single opportunity match explanation
    m_exp = client.get(f"/api/v1/member/opportunities/{ids['it_telangana_open']}/match", headers=h1)
    assert m_exp.status_code == 200
    assert m_exp.json()["eligibility"]["eligibility_status"] == "likely_match"
    assert "informational" in m_exp.json()["eligibility"]["disclaimer"].lower()

    # Unpublished opportunity returns 404 on member match endpoint
    assert client.get(f"/api/v1/member/opportunities/{ids['unverified_it_tender']}/match", headers=h1).status_code == 404

    # Save & view tracking for Member A
    sv = client.post(f"/api/v1/member/saved/{ids['it_telangana_open']}", headers=h1, json={"notes": "Prepare bid docs"})
    assert sv.status_code == 201
    vw1 = client.post(f"/api/v1/member/viewed/{ids['it_telangana_open']}", headers=h1)
    vw2 = client.post(f"/api/v1/member/viewed/{ids['it_telangana_open']}", headers=h1)
    assert vw1.status_code == 200 and vw2.json()["view_count"] == 2

    # Member B's saved and viewed lists remain completely empty (strict isolation)
    assert client.get("/api/v1/member/saved", headers=h2).json() == []
    assert client.get("/api/v1/member/viewed", headers=h2).json() == []
    assert len(client.get("/api/v1/member/saved", headers=h1).json()) == 1
    assert len(client.get("/api/v1/member/viewed", headers=h1).json()) == 1

    # Unsave works
    assert client.delete(f"/api/v1/member/saved/{ids['it_telangana_open']}", headers=h1).status_code == 204
    assert client.get("/api/v1/member/saved", headers=h1).json() == []


def test_admin_matching_controls_and_production_db_isolation():
    h_admin = _admin_headers()

    # 1. Review & update scoring weights
    cfg_before = client.get("/api/admin/matching/config", headers=h_admin)
    assert cfg_before.status_code == 200
    assert cfg_before.json()["sector_weight"] == 30.0

    cfg_upd = client.put(
        "/api/admin/matching/config",
        headers=h_admin,
        json={"sector_weight": 35.0, "geography_weight": 25.0},
    )
    assert cfg_upd.status_code == 200
    assert cfg_upd.json()["sector_weight"] == 35.0
    assert cfg_upd.json()["geography_weight"] == 25.0
    assert cfg_upd.json()["updated_by"] == "admin"

    # Restore default weights
    client.put("/api/admin/matching/config", headers=h_admin, json={"sector_weight": 30.0, "geography_weight": 20.0})

    # 2. List profiles & inspect recommendations
    profiles = client.get("/api/admin/matching/profiles", headers=h_admin)
    assert profiles.status_code == 200
    assert len(profiles.json()) >= 1
    pid = profiles.json()[0]["id"]

    insp = client.get(f"/api/admin/matching/inspect/{pid}", headers=h_admin)
    assert insp.status_code == 200
    assert len(insp.json()) >= 1
    oid = insp.json()[0]["opportunity"]["id"]

    # 3. Record & list false-positive feedback
    fb = client.post(
        "/api/admin/matching/feedback",
        headers=h_admin,
        json={
            "business_profile_id": pid,
            "opportunity_id": oid,
            "flag_type": "false_positive",
            "reason": "Audit test flag for review",
        },
    )
    assert fb.status_code == 201
    fb_list = client.get("/api/admin/matching/feedback?flag_type=false_positive", headers=h_admin)
    assert fb_list.status_code == 200
    assert any(r["id"] == fb.json()["id"] for r in fb_list.json())

    # 4. List incomplete-eligibility opportunities
    inc = client.get("/api/admin/matching/incomplete-eligibility", headers=h_admin)
    assert inc.status_code == 200
    assert len(inc.json()) >= 1

    # 5. Production DB isolation check: data/becci.db must NOT contain our test member account
    prod_db = Path("./data/becci.db")
    if prod_db.exists():
        conn = sqlite3.connect(str(prod_db))
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if "member_accounts" in tables:
            row = conn.execute("SELECT email FROM member_accounts WHERE email = 'member_a@becci-test.in'").fetchone()
            assert row is None
        conn.close()
