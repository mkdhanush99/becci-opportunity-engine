"""Tests for Tender Intelligence and extraction engine."""
from app.pipeline.tender_intelligence import extract_tender_intelligence, parse_numeric_inr


def test_parse_numeric_inr():
    assert parse_numeric_inr("Rs. 4.5 Crores") == 45000000.0
    assert parse_numeric_inr("25 Lakhs") == 2500000.0
    assert parse_numeric_inr("50,000") == 50000.0
    assert parse_numeric_inr("Not published") is None
    assert parse_numeric_inr(None) is None


def test_extract_tender_intelligence_comprehensive():
    text = """
    GOVERNMENT OF ANDHRA PRADESH - ROADS & BUILDINGS DEPARTMENT
    Tender Reference No: AP/RB/2026/CZ/104
    Work Description: Widening and strengthening of state highway corridor.
    Estimated Value: Rs. 12.50 Crores
    Earnest Money Deposit (EMD): Rs. 12,50,000. MSE and Udyam exemption allowed as per procurement policy.
    Tender Fee: Rs. 15,000
    Minimum Annual Turnover: Rs. 6.0 Crores
    Experience: 5 years experience in national highway or state road construction.
    Required Registrations: GST, PAN, EPF, Class-I Special Category Civil.
    """
    data = extract_tender_intelligence(text)
    assert data.reference_number == "AP/RB/2026/CZ/104"
    assert data.estimated_value_numeric == 125000000.0
    assert data.emd_numeric == 1250000.0
    assert data.msme_emd_exemption is True
    assert "GST Registration Certificate" in data.required_registrations
    assert "Permanent Account Number (PAN)" in data.required_registrations
    assert "Valid Class Contractor Registration" in data.required_registrations
    assert "₹125,000,000" in data.plain_language_summary
    assert len(data.document_evidence) >= 4
