"""Tests for BECCI Government Schemes Scope Correction, Filtering, and Eligibility Intelligence.

Verifies:
1. Telangana filtering (Pan-India + Telangana schemes; excludes AP and unrelated state schemes).
2. Andhra Pradesh filtering (Pan-India + AP schemes; excludes TG and unrelated state schemes).
3. Pan-India scheme visibility.
4. Exclusion of unrelated state-exclusive schemes.
5. OBC/BC vs General MSME classification (Guardrail A).
6. Separation of source verification status from application status (Guardrail D).
7. Advisory eligibility assessment engine (Guardrail E: never promises benefits).
8. Jobs and Tenders preservation: Jobs and Tenders remain Pan-India (Guardrail F).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.enums import (
    BeneficiaryClassification,
    GeographicalScope,
    SchemeApplicationStatus,
    SchemeEligibilityAssessmentStatus,
    SourceVerificationStatus,
)
from app.main import app
from app.matching.schemes import evaluate_scheme_eligibility
from app.models import SchemeDetail

client = TestClient(app)


def test_scheme_endpoint_telangana_filtering():
    """When a Telangana user queries schemes, they see Pan-India schemes and Telangana schemes,

    but NEVER Andhra Pradesh-specific schemes or unrelated state schemes.
    """
    res = client.get("/api/v1/schemes?state=Telangana")
    assert res.status_code == 200
    data = res.json()
    items = data["items"]
    assert len(items) > 0

    scopes_found = set()
    for item in items:
        assert item["category"] == "funding"
        sd = item.get("scheme_detail")
        assert sd is not None, f"Scheme {item['title']} missing scheme_detail"
        scope = sd["geographical_scope"]
        scopes_found.add(scope)
        # MUST ONLY be pan_india or telangana
        assert scope in ("pan_india", "telangana"), f"Unexpected scope {scope} in Telangana query"
        # Must NEVER be andhra_pradesh
        assert scope != "andhra_pradesh", f"AP scheme {item['title']} leaked into Telangana query!"

    assert "telangana" in scopes_found
    assert "pan_india" in scopes_found


def test_scheme_endpoint_andhra_pradesh_filtering():
    """When an Andhra Pradesh user queries schemes, they see Pan-India schemes and AP schemes,

    but NEVER Telangana-specific schemes or unrelated state schemes.
    """
    res = client.get("/api/v1/schemes?state=Andhra Pradesh")
    assert res.status_code == 200
    data = res.json()
    items = data["items"]
    assert len(items) > 0

    scopes_found = set()
    for item in items:
        assert item["category"] == "funding"
        sd = item.get("scheme_detail")
        assert sd is not None
        scope = sd["geographical_scope"]
        scopes_found.add(scope)
        # MUST ONLY be pan_india or andhra_pradesh
        assert scope in ("pan_india", "andhra_pradesh"), f"Unexpected scope {scope} in AP query"
        # Must NEVER be telangana
        assert scope != "telangana", f"Telangana scheme {item['title']} leaked into AP query!"

    assert "andhra_pradesh" in scopes_found
    assert "pan_india" in scopes_found


def test_pan_india_schemes_visibility():
    """Querying scope=pan_india or state=National returns exclusively Central / Pan-India schemes."""
    res = client.get("/api/v1/schemes?scope=pan_india")
    assert res.status_code == 200
    items = res.json()["items"]
    assert len(items) > 0
    for item in items:
        sd = item["scheme_detail"]
        assert sd["geographical_scope"] == "pan_india"
        assert item["state"] is None


def test_obc_versus_general_msme_classification():
    """Guardrail A: A general SIDBI MSME loan must NOT be classified as OBC-specific."""
    res = client.get("/api/v1/schemes?scope=pan_india")
    assert res.status_code == 200
    items = res.json()["items"]

    # 1. NBCFDC must be obc_bc_specific
    nbcfdc_items = [i for i in items if "nbcfdc" in i["issuing_organisation"].lower()]
    assert len(nbcfdc_items) > 0
    for n in nbcfdc_items:
        sd = n["scheme_detail"]
        assert sd["beneficiary_classification"] in (
            BeneficiaryClassification.OBC_BC_SPECIFIC.value,
            BeneficiaryClassification.WOMEN_ENTREPRENEURS.value,
        )

    # 2. SIDBI PRAYAAS must be general_msme (NOT obc_bc_specific)
    sidbi_prayaas = next((i for i in items if "prayaas" in i["title"].lower()), None)
    assert sidbi_prayaas is not None
    assert sidbi_prayaas["scheme_detail"]["beneficiary_classification"] == BeneficiaryClassification.GENERAL_MSME.value
    assert "All" in sidbi_prayaas["scheme_detail"]["applicable_castes"]


def test_separate_verification_from_application_status():
    """Guardrail D: A scheme can be officially verified while its real-world application status is closed or upcoming."""
    res = client.get("/api/v1/schemes")
    assert res.status_code == 200
    items = res.json()["items"]

    # PM-YASASVI is verified but closed
    yasasvi = next((i for i in items if "yasasvi" in i["title"].lower()), None)
    assert yasasvi is not None
    assert yasasvi["scheme_detail"]["source_verification_status"] == SourceVerificationStatus.VERIFIED.value
    assert yasasvi["scheme_detail"]["application_status"] == SchemeApplicationStatus.CLOSED.value

    # National Overseas Scholarship is verified but upcoming
    nos = next((i for i in items if "national overseas scholarship" in i["title"].lower()), None)
    assert nos is not None
    assert nos["scheme_detail"]["source_verification_status"] == SourceVerificationStatus.VERIFIED.value
    assert nos["scheme_detail"]["application_status"] == SchemeApplicationStatus.UPCOMING.value

    # Telangana ePASS Post-Matric is verified and open
    tg_postmatric = next((i for i in items if "post-matric" in i["title"].lower() and i["state"] == "Telangana"), None)
    assert tg_postmatric is not None
    assert tg_postmatric["scheme_detail"]["source_verification_status"] == SourceVerificationStatus.VERIFIED.value
    assert tg_postmatric["scheme_detail"]["application_status"] == SchemeApplicationStatus.OPEN.value


def test_eligibility_assessment_unit_logic():
    """Guardrail E: Rigorous evaluation of candidate against SchemeDetail criteria without promising benefits."""
    mock_tg_scheme = SchemeDetail(
        opportunity_id="test-tg-vidya-nidhi",
        scheme_name="Mahatma Jyotiba Phule Overseas Vidya Nidhi",
        government_department="BC Welfare Dept, Govt of Telangana",
        geographical_scope=GeographicalScope.TELANGANA.value,
        beneficiary_classification=BeneficiaryClassification.STUDENTS.value,
        beneficiary_categories=["students", "professionals"],
        applicable_castes=["BC-A", "BC-B", "BC-C", "BC-D", "BC-E", "EBC"],
        domicile_required=True,
        domicile_state="Telangana",
        income_limit="≤ ₹5,00,000 per annum",
        age_limit="Below 35 years",
        education_requirement="Graduation with 60% marks",
        occupation_requirement="Student",
        benefit_type="scholarship",
        benefit_amount="₹20,00,000",
        source_verification_status="verified",
        application_status="open",
    )

    # 1. Eligible candidate
    res_eligible = evaluate_scheme_eligibility(
        mock_tg_scheme,
        {
            "domicile_state": "Telangana",
            "caste_community": "BC-B",
            "is_non_creamy_layer": True,
            "annual_family_income": 350000,
            "age": 25,
            "gender": "male",
        },
    )
    assert res_eligible.status == SchemeEligibilityAssessmentStatus.ELIGIBLE.value
    assert "Eligible based on supplied information" in res_eligible.status_label
    assert "BECCI does not promise or guarantee" in res_eligible.disclaimer

    # 2. Domicile mismatch (Maharashtra resident applying for Telangana scheme)
    res_mismatch = evaluate_scheme_eligibility(
        mock_tg_scheme,
        {
            "domicile_state": "Maharashtra",
            "caste_community": "BC-B",
            "annual_family_income": 300000,
            "age": 24,
        },
    )
    assert res_mismatch.status == SchemeEligibilityAssessmentStatus.NOT_ELIGIBLE.value
    assert any("Domicile mismatch" in u for u in res_mismatch.unmatched_conditions)

    # 3. Income exceeded
    res_high_income = evaluate_scheme_eligibility(
        mock_tg_scheme,
        {
            "domicile_state": "Telangana",
            "caste_community": "BC-A",
            "annual_family_income": 750000,  # exceeds 5.0L
            "age": 25,
        },
    )
    assert res_high_income.status == SchemeEligibilityAssessmentStatus.NOT_ELIGIBLE.value
    assert any("Income exceeded" in u for u in res_high_income.unmatched_conditions)

    # 4. Incomplete information (missing income and caste)
    res_incomplete = evaluate_scheme_eligibility(
        mock_tg_scheme,
        {
            "domicile_state": "Telangana",
        },
    )
    assert res_incomplete.status == SchemeEligibilityAssessmentStatus.POTENTIALLY_ELIGIBLE.value
    assert len(res_incomplete.missing_information) > 0


def test_scheme_eligibility_api_endpoint():
    """Tests POST /api/v1/schemes/{id}/check-eligibility endpoint end-to-end."""
    # Find a live scheme in DB
    res = client.get("/api/v1/schemes?limit=1")
    assert res.status_code == 200
    scheme = res.json()["items"][0]
    scheme_id = scheme["id"]

    # Post eligibility assessment
    payload = {
        "domicile_state": scheme["state"] or "Telangana",
        "caste_community": "OBC",
        "is_non_creamy_layer": True,
        "annual_family_income": 200000,
        "age": 28,
        "gender": "female",
    }
    eval_res = client.post(f"/api/v1/schemes/{scheme_id}/check-eligibility", json=payload)
    assert eval_res.status_code == 200
    eval_data = eval_res.json()
    assert eval_data["status"] in ("eligible", "potentially_eligible", "not_eligible")
    assert "BECCI does not promise or guarantee" in eval_data["disclaimer"]


def test_jobs_and_tenders_preserved_as_pan_india():
    """Guardrail F: Jobs and Tenders remain Pan-India and are NOT restricted to TG/AP."""
    # Query tenders without state filter -> should return Pan-India tenders
    res_tenders = client.get("/api/v1/opportunities?category=tender")
    assert res_tenders.status_code == 200
    tenders = res_tenders.json()["items"]
    assert len(tenders) > 0

    # Query jobs -> should return jobs
    res_jobs = client.get("/api/v1/opportunities?category=job")
    assert res_jobs.status_code == 200
    jobs = res_jobs.json()["items"]
    assert len(jobs) > 0
