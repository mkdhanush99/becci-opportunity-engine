"""Comprehensive test suite for Phase 2 Agent 03 - Tender Scout & Phase 1 Regression."""
from __future__ import annotations

import datetime as dt
from pathlib import Path
import httpx
import pytest
from fastapi.testclient import TestClient

from app.agents.job_scout import build_mpsc_items, build_tgpsc_items
from app.agents.tender_scout import (
    NOT_PUBLISHED,
    NOT_STATED,
    TenderScout,
    build_cppp_item,
    build_gem_item_from_doc,
    classify_geography,
    classify_sector,
    classify_sidbi_notice,
    evaluate_tender_status,
    extract_eligibility_intelligence,
    parse_cppp_detail_page,
    parse_cppp_home_tables,
    parse_gem_html_cards,
    parse_gem_pdf_details,
    parse_sidbi_tender_rows,
)
from app.db import get_engine, session_scope
from app.enums import BECCISector, LifecycleStatus, ScanStatus, TenderStatus, VerificationStatus
from app.fetch.http_fetcher import BlockedError, FetchError, HttpFetcher
from app.fetch.robots import RobotsCache
from app.main import app
from app.migrations import list_applied_migrations, rollback_migration, run_migrations
from app.models import Opportunity, Source
from app.orchestrator.service import Orchestrator, SourceLockedError, register_agent
from app.pipeline.deduplication import handle_deduplication_and_changes
from app.pipeline.extraction import ExtractedItem, pdf_text
from app.pipeline.normalisation import normalise_item
from app.pipeline.verification import verify_opportunity

client = TestClient(app)


# --------------------------------------------------------------------------- 1-3. Tender Extraction & Missing Fields
def test_gem_extraction_with_pdf_and_missing_field_defaults():
    sample_doc = {
        "b_id": [10072869],
        "b_bid_number": ["GEM/2026/B/8193555"],
        "b_bid_type": [1],
        "bd_category_name": ["Custom Bid for Services - Soil Investigation for GRC Kamptee"],
        "b_total_quantity": [1],
        "ba_official_details_minName": ["Ministry of Defence"],
        "ba_official_details_deptName": ["Department of Military Affairs"],
        "final_start_date_sort": ["2026-11-18T12:00:00Z"],
        "final_end_date_sort": ["2026-12-19T12:44:00Z"],
    }
    # Without PDF -> missing financial fields must explicitly say 'Not published' / 'Not stated'
    item_no_pdf = build_gem_item_from_doc(sample_doc, pdf_str="")
    assert item_no_pdf.fields["estimated_value"] == NOT_PUBLISHED
    assert item_no_pdf.fields["emd_amount"] == NOT_PUBLISHED
    assert item_no_pdf.fields["turnover_requirement"] == NOT_STATED
    assert item_no_pdf.fields["experience_requirement"] == NOT_STATED

    # With PDF text -> extracts estimated value, EMD, turnover, experience, MSE relaxation, and evidence
    sample_pdf_text = """
    Bid End Date/Time 09-11-2026 18:00:00
    Bid Opening Date/Time 10-11-2026 18:00:00
    Organisation Name Indian Army Office Name ***
    Minimum Average Annual Turnover of the bidder (For the last 3 Financial Years) 10 Lakh (s)
    Years of Past Experience Required for same/similar service 2 Year (s)
    MSE Relaxation for Years Of Experience and Turnover Yes | Complete
    Dated : 29-10-2026
    Estimated Bid Value in INR (Inclusive of all taxes) 1923400
    EMD Amount 57702
    Purchase preference to Micro and Small Enterprises (MSEs): Purchase preference will be given to MSEs having valid Udyam Certificate
    """
    item_pdf = build_gem_item_from_doc(sample_doc, pdf_str=sample_pdf_text)
    assert item_pdf.fields["estimated_value"] == "INR 1923400"
    assert item_pdf.fields["emd_amount"] == "INR 57702"
    assert item_pdf.fields["turnover_requirement"] == "10 Lakh (s)"
    assert item_pdf.fields["experience_requirement"] == "2 Year (s)"
    assert "MSE Relaxation" in item_pdf.fields["msme_preference"]
    assert "MSE Purchase Preference" in item_pdf.fields["msme_preference"]
    assert item_pdf.fields["tender_status"] == TenderStatus.EXTENDED.value  # PDF deadline 09-11-2026 < card deadline 19-12-2026
    assert item_pdf.fields["state"] == "Maharashtra"  # Kamptee -> Maharashtra
    assert any(c.field == "estimated_value" for c in item_pdf.claims)
    assert any(c.field == "emd_amount" for c in item_pdf.claims)


def test_cppp_home_and_detail_extraction():
    home_html = """
    <html><body>
      <table>
        <tr><td>Tender Title</td><td>Reference No</td><td>Closing Date</td><td>Bid Opening Date</td></tr>
        <tr>
          <td><a href="/eprocure/app?component=$DirectLink&page=Home&service=direct&sp=S1">1. Special Repairs of Slope Protection Work along Varandh Ghat in Maharashtra</a></td>
          <td>NIT No.24/EENHD/PEN/3277/2026-27</td>
          <td>18-Dec-2026 05:30 PM</td>
          <td>21-Dec-2026 12:00 PM</td>
        </tr>
      </table>
      <table>
        <tr><td>Corrigendum Title</td><td>Reference No</td><td>Closing Date</td><td>Bid Opening Date</td></tr>
        <tr>
          <td><a href="/eprocure/app?component=$DirectLink_0&page=Home">1. Date Extended for High-Fidelity Simulator</a></td>
          <td>PI(EP)/26-27/G/02/27</td>
          <td>14-Dec-2026 12:00 PM</td>
          <td>15-Dec-2026 12:00 PM</td>
        </tr>
      </table>
    </body></html>
    """
    tenders, corrs = parse_cppp_home_tables(home_html)
    assert len(tenders) == 1
    assert len(corrs) == 1
    assert tenders[0]["reference_number"] == "NIT No.24/EENHD/PEN/3277/2026-27"

    detail_html = """
    <html><body>
      <table>
        <tr><td>Organisation Chain</td><td>Ministry of Road Transport and Highways||RO Mumbai - MoRTH||NH Maharashtra PWD-Pen</td></tr>
        <tr><td>Tender Reference Number</td><td>NIT No.24/EENHD/PEN/3277/2026-27</td><td>Tender ID</td><td>2026_MoRTH_934941_1</td></tr>
        <tr><td>Tender Category</td><td>Works</td><td>Product Category</td><td>Civil Works</td></tr>
        <tr><td>Tender Fee in ₹</td><td>10,000</td><td>EMD Amount in ₹</td><td>16,04,000</td></tr>
        <tr><td>Tender Value in ₹</td><td>8,02,01,914</td><td>Location</td><td>PEN</td></tr>
        <tr><td>Published Date</td><td>19-Nov-2026 12:30 PM</td><td>Bid Submission End Date</td><td>18-Dec-2026 05:30 PM</td></tr>
        <tr><td>Pre Bid Meeting Date</td><td>11-Dec-2026 03:00 PM</td><td>Pre Bid Meeting Address</td><td>Navi Mumbai 400614</td></tr>
        <tr><td>NDA/Pre Qualification</td><td>BHARAT KOSH TENDER FEE POWER OF ATTORNEY BID SECURITY GST REVERSE MECHANISM</td></tr>
      </table>
      <a href="/doc/Tendernotice_1.pdf">Tendernotice_1.pdf</a>
    </body></html>
    """
    kv = parse_cppp_detail_page(detail_html)
    item = build_cppp_item(tenders[0], detail_kv=kv, corrigendums=corrs)
    assert item.external_key == "cppp:2026_MoRTH_934941_1"
    assert item.fields["estimated_value"] == "INR 8,02,01,914"
    assert item.fields["emd_amount"] == "INR 16,04,000"
    assert item.fields["tender_fee"] == "INR 10,000"
    assert item.fields["state"] == "Maharashtra"
    assert item.fields["sector"] == BECCISector.CONSTRUCTION_INFRASTRUCTURE.value
    assert item.fields["pre_bid_date"] == "2026-12-11"
    assert "GST Registration" in item.fields["required_registrations"]


def test_sidbi_tenders_filters_sarfaesi_auctions():
    sidbi_html = """
    <html><body>
      <table>
        <tr><th>S. No.</th><th>Title</th><th>Tender Date</th><th>Last Date Of Submission</th><th>Remark</th></tr>
        <tr>
          <td>1</td>
          <td><a href="tenders/tenderarchived/tenderdetails/sarfaesi-sale-1">E-Auction Sale Notice for sale of immovable property under SARFAESI Act, 2002 – Syamala Pipe</a></td>
          <td>18/11/2026</td><td>04/12/2026</td><td>Last Date: Dec 04, 2026</td>
        </tr>
        <tr>
          <td>2</td>
          <td><a href="tenders/tenderarchived/tenderdetails/rfp-data-aggregator">Request for Proposal (RFP) for Subscription of Data Aggregator services Provider</a></td>
          <td>16/11/2026</td><td>09/12/2026</td><td>Last Date: Dec 09, 2026</td>
        </tr>
      </table>
    </body></html>
    """
    items = parse_sidbi_tender_rows(sidbi_html)
    assert len(items) == 2
    assert items[0].skip_reason is not None and "SARFAESI" in items[0].skip_reason
    assert items[1].skip_reason is None
    assert items[1].fields["sector"] == BECCISector.IT_TECHNOLOGY.value
    assert items[1].fields["deadline"] == "2026-12-09"


# --------------------------------------------------------------------------- 4-7. Deadlines, Corrigendums, Cancellations & Deduplication
def test_deadline_monitoring_states():
    today = dt.date(2026, 11, 19)
    assert evaluate_tender_status(dt.date(2026, 11, 10), today=today) == TenderStatus.EXPIRED.value
    assert evaluate_tender_status(dt.date(2026, 11, 23), today=today) == TenderStatus.CLOSING_SOON.value
    assert evaluate_tender_status(dt.date(2026, 12, 20), today=today) == TenderStatus.OPEN.value
    assert evaluate_tender_status(dt.date(2026, 12, 20), opening_date=dt.date(2026, 11, 25), today=today) == TenderStatus.UPCOMING.value
    assert evaluate_tender_status(dt.date(2026, 12, 20), is_extended=True, today=today) == TenderStatus.EXTENDED.value
    assert evaluate_tender_status(dt.date(2026, 12, 20), is_cancelled=True, today=today) == TenderStatus.CANCELLED.value
    assert evaluate_tender_status(None, today=today) == TenderStatus.UNDER_VERIFICATION.value


def test_corrigendum_extension_and_cancellation_lifecycle():
    with session_scope() as session:
        src = session.get(Source, "cppp-eprocure")
        entry = {
            "title": "Supply and Installation of Medical Laparoscopic Surgery Set",
            "reference_number": "PI(EP)/26-27/G/02/99",
            "closing_raw": "01-Dec-2026",
            "opening_raw": "02-Dec-2026",
            "detail_url": None,
        }
        item1 = build_cppp_item(entry, detail_kv={"Tender ID": "2026_HLTH_999_1"})
        opp1 = normalise_item(item1, src, "tender_scout", is_fixture=True)
        action1, saved1 = handle_deduplication_and_changes(session, opp1)
        verify_opportunity(session, saved1, src)
        session.flush()
        assert action1 == "inserted"
        assert saved1.tender_detail is not None
        assert saved1.tender_detail.tender_status == "open"

        # Now a corrigendum extends the closing date to 15-Dec-2026
        corrs_ext = [
            {
                "title": "Date Extended for Laparoscopic Surgery Set",
                "reference_number": "PI(EP)/26-27/G/02/99",
                "closing_raw": "15-Dec-2026",
                "opening_raw": "16-Dec-2026",
            }
        ]
        item2 = build_cppp_item(entry, detail_kv={"Tender ID": "2026_HLTH_999_1"}, corrigendums=corrs_ext)
        opp2 = normalise_item(item2, src, "tender_scout", is_fixture=True)
        action2, saved2 = handle_deduplication_and_changes(session, opp2)
        verify_opportunity(session, saved2, src)
        session.flush()
        assert action2 == "updated"
        assert saved2.id == saved1.id
        assert saved2.deadline == dt.date(2026, 12, 15)
        assert saved2.tender_detail.tender_status == "extended"
        assert len(saved2.tender_detail.corrigendum_history) >= 1
        assert len(saved2.versions) == 2

        # Now a cancellation corrigendum arrives
        corrs_cancel = [
            {
                "title": "Tender Cancelled due to administrative reasons",
                "reference_number": "PI(EP)/26-27/G/02/99",
                "closing_raw": "15-Dec-2026",
                "opening_raw": "16-Dec-2026",
            }
        ]
        item3 = build_cppp_item(entry, detail_kv={"Tender ID": "2026_HLTH_999_1"}, corrigendums=corrs_cancel)
        opp3 = normalise_item(item3, src, "tender_scout", is_fixture=True)
        action3, saved3 = handle_deduplication_and_changes(session, opp3)
        v_rec = verify_opportunity(session, saved3, src)
        session.flush()
        assert action3 == "updated"
        assert saved3.tender_detail.tender_status == "cancelled"
        assert saved3.lifecycle_status == LifecycleStatus.WITHDRAWN
        assert v_rec.status == VerificationStatus.REMOVED


# --------------------------------------------------------------------------- 8-10. Eligibility, Sector & Geography Classification
def test_all_11_becci_sectors_classification():
    assert classify_sector("Laparoscopic Surgery Set for Hospital") == BECCISector.HEALTHCARE.value
    assert classify_sector("Procurement of Fiber Network Cards and Cohesity Software") == BECCISector.IT_TECHNOLOGY.value
    assert classify_sector("Special Repairs of Slope Protection Work along NH-965 Civil Works") == BECCISector.CONSTRUCTION_INFRASTRUCTURE.value
    assert classify_sector("High-Fidelity Simulator System for University Classroom Training") == BECCISector.EDUCATION_TRAINING.value
    assert classify_sector("Supply of Seed and Dairy Irrigation Equipment for Agriculture") == BECCISector.AGRICULTURE_ALLIED.value
    assert classify_sector("RFP Selection of Consultancy Agency and Auditor for PMU") == BECCISector.FINANCE_PROFESSIONAL.value
    assert classify_sector("Catering and Canteen Guest House Hospitality Services") == BECCISector.HOSPITALITY_TOURISM.value
    assert classify_sector("LED Luminaire and Hydrochloric Acid Manufacturing Plant") == BECCISector.MANUFACTURING.value
    assert classify_sector("Supply of Waste Container, Office Chairs and Stationery") == BECCISector.TRADING_DISTRIBUTION.value
    assert classify_sector("Hiring of Security Agency and Annual Maintenance Contract") == BECCISector.SERVICES.value
    assert classify_sector("Miscellaneous Uncategorised Notice", tender_category="Unknown") == BECCISector.OTHER.value


def test_geographic_and_eligibility_intelligence():
    st, city, loc_type = classify_geography("Periodical Services at Nagarjuna sagar, Hyderabad")
    assert st == "Telangana"
    assert city == "Hyderabad"
    assert loc_type == "local"

    st2, city2, loc_type2 = classify_geography("All India Supply of Equipment", org_chain="Ministry of Defence")
    assert st2 is None
    assert loc_type2 == "national"

    intel = extract_eligibility_intelligence(
        "Minimum Average Annual Turnover of the bidder 25 Lakh(s). "
        "Years of Past Experience Required 3 Year(s). "
        "Purchase preference to Micro and Small Enterprises (MSEs) having valid Udyam Certificate. "
        "The bidder must be the manufacturer / OEM. GSTIN and PAN Card required. Joint Venture (JV) not permitted."
    )
    assert "25 Lakh" in intel["turnover_conditions"]
    assert "3 Year" in intel["experience_conditions"]
    assert "Udyam" in intel["udyam_registration"]
    assert "GST Registration" in intel["required_registrations"]
    assert "PAN" in intel["required_registrations"]
    assert "Manufacturer / OEM Authorization" in intel["required_registrations"]
    assert "Joint Venture" in intel["consortium_jv_permissions"]


# --------------------------------------------------------------------------- 11-14. Verification, SSRF, Robots.txt & Invalid Files
def test_robots_txt_blocks_mahatenders_and_invalid_pdf_handling():
    def mock_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, headers={"content-type": "text/plain"}, text="User-agent: *\nDisallow: /\n")
        return httpx.Response(200, text="<html>OK</html>")

    transport = httpx.MockTransport(mock_handler)
    rc = RobotsCache(client_factory=lambda: httpx.Client(transport=transport))
    fetcher = HttpFetcher(["mahatenders.gov.in"], robots=rc, transport=transport, check_dns=False)
    with pytest.raises(BlockedError, match="disallowed by robots.txt"):
        fetcher.get("https://mahatenders.gov.in/nicgep/app")
    fetcher.close()

    # Corrupt / non-PDF bytes handled safely without crashing
    assert pdf_text(b"not a valid pdf file at all") == ""


# --------------------------------------------------------------------------- 15-17. API Authorisation, Migrations & DB Isolation
def test_tender_public_and_admin_apis_and_migrations():
    # Verify migrations table
    applied = list_applied_migrations(get_engine())
    versions = [m["version"] for m in applied]
    assert "002_phase2_tender_details" in versions

    # Login as admin
    login_res = client.post("/api/admin/auth/login", json={"username": "admin", "password": "BecciAdmin2026!"})
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Insert a verified non-fixture tender in test DB
    with session_scope() as session:
        src = session.get(Source, "cppp-eprocure")
        entry = {
            "title": "Periodical Services to Various Buildings at Nagarjuna Sagar, Hyderabad",
            "reference_number": "CCEESTS/ENQ/PS/N_SAGAR/HYD/79/2026-27",
            "closing_raw": "10-Dec-2026",
            "opening_raw": "11-Dec-2026",
            "detail_url": None,
        }
        item = build_cppp_item(entry, detail_kv={"Tender ID": "2026_DRDO_79_1", "Tender Value in ₹": "45,00,000"})
        opp = normalise_item(item, src, "tender_scout", is_fixture=False)
        session.add(opp)
        verify_opportunity(session, opp, src)
        session.commit()
        opp_id = opp.id

    # Unpublished tender must NOT appear on public /api/v1/tenders
    pub_before = client.get("/api/v1/tenders?state=Telangana")
    assert pub_before.status_code == 200
    assert opp_id not in [i["id"] for i in pub_before.json()["items"]]

    # Admin can view and filter in /api/admin/tenders
    adm_list = client.get("/api/admin/tenders?state=Telangana&q=Nagarjuna", headers=headers)
    assert adm_list.status_code == 200
    assert any(i["id"] == opp_id for i in adm_list.json())

    # Admin can inspect full tender detail + evidence
    adm_detail = client.get(f"/api/admin/tenders/{opp_id}", headers=headers)
    assert adm_detail.status_code == 200
    assert adm_detail.json()["tender_detail"]["estimated_value"] == "INR 45,00,000"
    assert any(c["name"] == "tender_reference_consistency" and c["passed"] for c in adm_detail.json()["verification_records"][0]["checks"])

    # Publish via admin review
    rev = client.post(
        f"/api/admin/opportunities/{opp_id}/review",
        json={"action": "publish", "reason": "Approved Telangana tender"},
        headers=headers,
    )
    assert rev.status_code == 200

    # Now appears on public /api/v1/tenders with filters
    pub_after = client.get("/api/v1/tenders?state=Telangana&q=CCEESTS")
    assert pub_after.status_code == 200
    assert any(i["id"] == opp_id for i in pub_after.json()["items"])

    # Production DB isolation check: data/becci.db must not contain our test record
    prod_db = Path("./data/becci.db")
    if prod_db.exists():
        import sqlite3
        conn = sqlite3.connect(str(prod_db))
        row = conn.execute("SELECT id FROM opportunities WHERE id = ?", (opp_id,)).fetchone()
        conn.close()
        assert row is None


# --------------------------------------------------------------------------- 18-20. Scheduling, Failure Recovery, Locking & Phase 1 Regression
def test_scheduler_locking_retry_and_failure_isolation():
    calls = {"flaky": 0}

    def flaky_parser(source: Source, ctx) -> list[ExtractedItem]:
        calls["flaky"] += 1
        if calls["flaky"] == 1:
            raise FetchError("simulated transient HTTP 503 timeout")
        entry = {
            "title": "Supply of Solar LED Street Luminaires",
            "reference_number": "SOLAR/2026/01",
            "closing_raw": "20-Dec-2026",
            "opening_raw": "21-Dec-2026",
            "detail_url": None,
        }
        return [build_cppp_item(entry, detail_kv={"Tender ID": "2026_SOLAR_01"})]

    TenderScout.parsers["test_flaky_tender"] = flaky_parser

    with session_scope() as session:
        flaky_src = Source(
            id="flaky-tender-src",
            name="Flaky Tender Portal",
            domain="eprocure.gov.in",
            url="https://eprocure.gov.in/eprocure/app",
            agent_id="tender_scout",
            parser="test_flaky_tender",
            categories=["tender"],
            geographic_coverage=["National"],
            industry_relevance=["Manufacturing"],
            collection_method="http_html",
            reliability="official_government",
            issuing_organisation="Test Ministry",
            official_domains=["eprocure.gov.in"],
            active=True,
        )
        session.merge(flaky_src)
        session.commit()

        orch = Orchestrator(session)
        # Test lock contention
        owner = orch.acquire_lock("scan:flaky-tender-src")
        with pytest.raises(SourceLockedError):
            orch.run_source_scan("flaky-tender-src")
        orch.release_lock("scan:flaky-tender-src", owner)

        # Test retry with exponential backoff recovers on attempt 2
        run = orch.run_source_scan("flaky-tender-src", max_attempts=2, backoff_base_seconds=0.01)
        assert run.status == ScanStatus.SUCCESS
        assert run.attempt == 2
        assert run.items_new == 1


def test_phase1_agents_regression():
    # Phase 1 JobScout TGPSC & MPSC deterministic regression
    tg_entries = [
        {
            "kind": "notice",
            "title": "GENERAL RECRUITMENT FOR THE POST OF MANDAL PLANNING OFFICERS NOTIFICATION NO. 07/G/ES/2026 - NOTIFICATION",
            "url": "https://websitenew.tgpsc.gov.in/preview/doc1",
        },
        {
            "kind": "notice",
            "title": "HOSTING OF KEY FOR DEPUTY EDUCATIONAL OFFICERS NOTIFICATION NO. 03/G/SE/2026 - WEB NOTE",
            "url": "https://websitenew.tgpsc.gov.in/preview/doc2",
        },
    ]
    tg_items = build_tgpsc_items(tg_entries, "https://websitenew.tgpsc.gov.in/", None, fetch_docs=False)
    real_tg = [i for i in tg_items if not i.skip_reason]
    skipped_tg = [i for i in tg_items if i.skip_reason]
    assert len(real_tg) == 1
    assert real_tg[0].fields["reference_number"] == "07/G/ES/2026"
    assert len(skipped_tg) == 1

    mpsc_rows = [
        {"advt_no": "022/2026", "subject": "Advt.No. 022/2026- Assistant (Legal), Group B - Advertisement", "date": "23-10-2026"},
        {"advt_no": "017/2026", "subject": "Advt. No. 017/2026 Combine Prelim - Corrigendum", "date": "17-11-2026"},
    ]
    mpsc_items = build_mpsc_items(mpsc_rows, "https://mpsc.gov.in/adv_notification/8")
    real_mpsc = [i for i in mpsc_items if not i.skip_reason]
    assert len(real_mpsc) == 1
    assert real_mpsc[0].fields["published_date"] == "2026-10-23"


# --------------------------------------------------------------------------- 21-24. Phase 2 Acceptance Audit Remediation Tests
def test_remediation_1_it_sector_keyword_classification():
    # Three SIDBI IT opportunities must classify under IT and technology
    t1 = "Request for Proposal for Procurement of High-End Laptops"
    t2 = "Request for Proposal for Technology refresh of Security Solutions"
    t3 = "Renewal of Subscription of M365 Licenses"

    assert classify_sector(t1, product_category=t1, tender_category="Goods", title=t1) == BECCISector.IT_TECHNOLOGY.value
    assert classify_sector(t2, product_category=t2, tender_category="Goods", title=t2) == BECCISector.IT_TECHNOLOGY.value
    assert classify_sector(t3, product_category=t3, tender_category="Goods", title=t3) == BECCISector.IT_TECHNOLOGY.value

    # Guard against broad matching: physical security agency & general goods must not misclassify as IT
    physical_sec = "Hiring of Security Agency at SIDBI Lucknow"
    assert (
        classify_sector(physical_sec, product_category=physical_sec, tender_category="Services", title=physical_sec)
        == BECCISector.SERVICES.value
    )


def test_remediation_2_product_category_precedence_over_buyer_ministry():
    # GeM record GEM/2025/B/5894420: Interactive Display Screen 86 inch bought by Ministry of Health and Family Welfare
    gem_doc = {
        "b_id": [7318868],
        "b_bid_number": ["GEM/2025/B/5894420"],
        "b_bid_type": [1],
        "bd_category_name": ["Interactive Display Screen 86 inch"],
        "b_total_quantity": [2],
        "ba_official_details_minName": ["Ministry of Health and Family Welfare"],
        "ba_official_details_deptName": ["Department of Health and Family Welfare"],
        "final_start_date_sort": ["2025-01-30T16:40:09Z"],
        "final_end_date_sort": ["2026-11-30T17:00:00Z"],
    }
    pdf_excerpt = """
    Ministry/State Name Ministry of Health and Family Welfare
    Department Name Department of Health and Family Welfare
    Organisation Name All India Institute of Medical Sciences (AIIMS) Office Name Raipur
    Item Category Interactive Display Screen 86 inch
    """
    item = build_gem_item_from_doc(gem_doc, pdf_str=pdf_excerpt)
    assert item.fields["sector"] == BECCISector.IT_TECHNOLOGY.value
    assert item.fields["industry"] == BECCISector.IT_TECHNOLOGY.value

    # Genuine healthcare product from the same ministry still classifies as Healthcare
    assert (
        classify_sector(
            "Supply of Laparoscopic Surgery Set",
            product_category="Medical Equipments",
            tender_category="Goods",
            title="Supply of Laparoscopic Surgery Set",
            buyer_text="Ministry of Health and Family Welfare",
        )
        == BECCISector.HEALTHCARE.value
    )

    # CPPP TIFR Miscellaneous Goods tender does not regress to Education due to buyer 'Institute'
    assert (
        classify_sector(
            "87-217 G Plan Apo 50X Objective Mitutoyo Microscope Objective",
            product_category="Miscellaneous Goods",
            tender_category="Goods",
            title="87-217 G Plan Apo 50X Objective Mitutoyo Microscope Objective",
            buyer_text="Tata Institute of Fundamental Research",
        )
        == BECCISector.TRADING_DISTRIBUTION.value
    )


def test_remediation_3_gem_pdf_bilingual_turnover_variants_and_org_na_guard():
    # Variant 1: Bidder Average Annual Turnover only
    pdf_bidder = """
    Organisation Name Indian Army Office Name ***
    Minimum Average Annual Turnover of the bidder (For the last 3 Financial Years) 10 Lakh (s)
    """
    f1, c1 = parse_gem_pdf_details(pdf_bidder)
    assert f1["turnover_field_variant"] == "bidder_average_annual_turnover"
    assert f1["bidder_turnover_requirement"] == "10 Lakh (s)"
    assert "oem_turnover_requirement" not in f1
    assert f1["turnover_requirement"] == "10 Lakh (s)"
    assert f1["organisation_name"] == "Indian Army"

    # Variant 2: OEM Average Turnover (Last 3 Years) + Organisation Name: N/a
    pdf_oem = """
    Ministry/State Name Uttar Pradesh
    Department Name Urban Development Department Uttar Pradesh
    Organisation Name N/a Office Name Nagar Nigam Aligarh
    OEM Average Turnover (Last 3 Years) 10 Lakh (s)
    Years of Past Experience Required for same/similar service 3 Year (s)
    """
    f2, c2 = parse_gem_pdf_details(pdf_oem)
    assert f2["turnover_field_variant"] == "oem_average_turnover_3yr"
    assert f2["oem_turnover_requirement"] == "10 Lakh (s)"
    assert "bidder_turnover_requirement" not in f2
    assert f2["turnover_requirement"] == "OEM Average Turnover (Last 3 Years): 10 Lakh (s)"
    assert "organisation_name" not in f2
    assert not any(cl.field == "issuing_organisation" for cl in c2)
    assert any(cl.field == "oem_turnover_requirement" for cl in c2)

    # Variant 3: Both Bidder Turnover and OEM Average Turnover present -> kept distinct
    pdf_both = """
    Minimum Average Annual Turnover of the bidder (For the last 3 Financial Years) 5 Lakh (s)
    OEM Average Turnover (Last 3 Years) 25 Lakh (s)
    """
    f3, c3 = parse_gem_pdf_details(pdf_both)
    assert f3["turnover_field_variant"] == "both_bidder_and_oem_turnover"
    assert f3["bidder_turnover_requirement"] == "5 Lakh (s)"
    assert f3["oem_turnover_requirement"] == "25 Lakh (s)"
    assert "Bidder Turnover: 5 Lakh (s)" in f3["turnover_requirement"]
    assert "OEM Average Turnover (Last 3 Years): 25 Lakh (s)" in f3["turnover_requirement"]

    # Variant 4: Missing / invalid turnover -> do not infer
    pdf_missing = """
    Organisation Name N/A Office Name Test Office
    EMD Detail Required No
    """
    f4, c4 = parse_gem_pdf_details(pdf_missing)
    assert "turnover_field_variant" not in f4
    assert "turnover_requirement" not in f4
    assert "organisation_name" not in f4


def test_remediation_4_sidbi_notice_classification_and_routing():
    # 1. Genuine procurement RFP
    c_rfp = classify_sidbi_notice("Request for Proposal for Procurement of High-End Laptops")
    assert c_rfp["notice_type"] == "procurement_rfp"
    assert c_rfp["routed_category"] == "tender"
    assert c_rfp["is_tender"] is True

    # 2. Vendor empanelment
    c_emp = classify_sidbi_notice("Empanelment of Implementing Agencies (IAs) under the MoRE Program")
    assert c_emp["notice_type"] == "vendor_empanelment"
    assert c_emp["routed_category"] == "tender"
    assert c_emp["tender_category"] == "Empanelment"

    # 3. Innovation challenge fund
    c_icf = classify_sidbi_notice("SIDBI Innovation Challenge Fund 2nd Cohort Applications Open")
    assert c_icf["notice_type"] == "innovation_challenge_fund"
    assert c_icf["routed_category"] == "funding"
    assert c_icf["subcategory"] == "innovation_challenge"
    assert c_icf["is_tender"] is False

    # 4. Funding application announcement
    c_fund = classify_sidbi_notice("Seed Fund Applications Open for MSME CleanTech Cohort")
    assert c_fund["notice_type"] == "funding_application_announcement"
    assert c_fund["routed_category"] == "funding"
    assert c_fund["subcategory"] == "funding_programme"
    assert c_fund["is_tender"] is False

    # 5. Ambiguous SIDBI notice
    c_amb = classify_sidbi_notice("General Institutional Stakeholder Consultation Notice 2026")
    assert c_amb["notice_type"] == "ambiguous_sidbi_notice"
    assert c_amb["manual_review_required"] is True

    # Verify end-to-end HTML table parsing and normalisation for all 5 types
    html = """
    <html><body><table>
      <tr><th>S. No.</th><th>Title</th><th>Tender Date</th><th>Last Date</th><th>Remark</th></tr>
      <tr><td>1</td><td><a href="tenders/rfp-laptops">Request for Proposal for Procurement of High-End Laptops</a></td><td>04/11/2026</td><td>25/11/2026</td><td></td></tr>
      <tr><td>2</td><td><a href="tenders/emp-more">Empanelment of Implementing Agencies (IAs) under the MoRE Program</a></td><td>16/11/2026</td><td>08/12/2026</td><td></td></tr>
      <tr><td>3</td><td><a href="tenders/icf-2nd-cohort">SIDBI Innovation Challenge Fund 2nd Cohort Applications Open</a></td><td>30/10/2026</td><td>30/11/2026</td><td></td></tr>
      <tr><td>4</td><td><a href="tenders/seed-fund-open">Seed Fund Applications Open for MSME CleanTech Cohort</a></td><td>01/11/2026</td><td>30/11/2026</td><td></td></tr>
      <tr><td>5</td><td><a href="tenders/general-notice">General Institutional Stakeholder Consultation Notice 2026</a></td><td>05/11/2026</td><td>28/11/2026</td><td></td></tr>
    </table></body></html>
    """
    parsed = parse_sidbi_tender_rows(html)
    assert len(parsed) == 5

    with session_scope() as session:
        src = session.get(Source, "sidbi-tenders")
        opp_rfp = normalise_item(parsed[0], src, "tender_scout", is_fixture=True)
        opp_emp = normalise_item(parsed[1], src, "tender_scout", is_fixture=True)
        opp_icf = normalise_item(parsed[2], src, "tender_scout", is_fixture=True)
        opp_fnd = normalise_item(parsed[3], src, "tender_scout", is_fixture=True)
        opp_amb = normalise_item(parsed[4], src, "tender_scout", is_fixture=True)

        assert opp_rfp.category == "tender" and opp_rfp.tender_detail is not None
        assert opp_rfp.tender_detail.sector == BECCISector.IT_TECHNOLOGY.value
        assert opp_emp.category == "tender" and opp_emp.tender_detail.tender_category == "Empanelment"
        assert opp_icf.category == "funding" and opp_icf.subcategory == "innovation_challenge"
        assert opp_icf.tender_detail is None and len(opp_icf.evidence) >= 4
        assert opp_fnd.category == "funding" and opp_fnd.subcategory == "funding_programme"
        assert opp_fnd.tender_detail is None and len(opp_fnd.evidence) >= 4
        assert opp_amb.category == "tender" and opp_amb.tender_detail.tender_status == TenderStatus.UNDER_VERIFICATION.value
        assert opp_amb.tender_detail.eligibility_intelligence["ambiguous_flag"] is True

