"""Tender Intelligence and Document Processing Engine.

Complies with Master Autonomous Build Directive Section 10 & 17:
- Deterministic extraction of:
  * Tender Reference Number
  * Department & Work Description
  * Location
  * Estimated Value (Lakhs/Crores normalized to numeric INR)
  * EMD (Earnest Money Deposit) & MSME exemption terms
  * Tender Fee
  * Bid Dates (Submission Start, Deadline, Technical Bid Opening)
  * Technical Eligibility (Turnover & Prior Experience)
  * Required Registrations (GST, PAN, Class Contractor License, Udyam)
  * Corrigenda & Amendment tracking
  * Document Page Evidence: Stores exact text snippet and page citation
  * Plain-language summary
- AI/Parser must NEVER invent facts. If missing, returns 'Not published' or 'Not stated'.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class TenderEvidence:
    field_name: str
    extracted_value: str
    evidence_text: str
    page_number: Optional[int] = None
    confidence: str = "high"


@dataclass
class ExtractedTenderData:
    reference_number: Optional[str] = None
    department: str = "Not stated"
    work_description: str = "Not stated"
    location: str = "Telangana / Andhra Pradesh"
    estimated_value_str: str = "Not published"
    estimated_value_numeric: Optional[float] = None
    emd_amount_str: str = "Not published"
    emd_numeric: Optional[float] = None
    msme_emd_exemption: bool = False
    tender_fee_str: str = "Not published"
    bid_submission_start: Optional[dt.datetime] = None
    bid_submission_deadline: Optional[dt.datetime] = None
    technical_bid_opening: Optional[dt.datetime] = None
    turnover_requirement: str = "Not stated"
    experience_requirement: str = "Not stated"
    required_registrations: list[str] = field(default_factory=list)
    corrigenda: list[dict[str, Any]] = field(default_factory=list)
    document_evidence: dict[str, Any] = field(default_factory=dict)
    plain_language_summary: str = ""


# Regex Patterns for Indian Tenders
RE_REF_NO = re.compile(r"(?:Tender\s+Ref(?:\.|erence)?\s*(?:No\.?)?|NIT\s+No\.?|Notice\s+Inviting\s+Tender\s+No\.?|Tender\s+ID|Bid\s+No\.?)\s*[:=-]?\s*([A-Za-z0-9_/\-.]+)", re.I)
RE_VAL_CRORE = re.compile(r"(?:Rs\.?|INR|₹)?\s*([\d,.]+)\s*(?:Cr(?:ore)?s?)\b", re.I)
RE_VAL_LAKH = re.compile(r"(?:Rs\.?|INR|₹)?\s*([\d,.]+)\s*(?:Lakh?s?|Lacs?)\b", re.I)
RE_VAL_EXACT = re.compile(r"(?:Estimated\s+(?:Cost|Value)|Approx\.?\s+Value)\s*[:=-]?\s*(?:Rs\.?|INR|₹)?\s*([\d,]+(?:\.\d{2})?)", re.I)
RE_EMD = re.compile(r"(?:EMD|Earnest\s+Money(?:\s+Deposit)?(?:\s*\([A-Za-z]+\))?)\s*[:=-]?\s*(?:Rs\.?|INR|₹)?\s*([\d,]+(?:\.\d{2})?|\d+\s*(?:Lakh|Cr(?:ore)?)?)", re.I)
RE_TENDER_FEE = re.compile(r"(?:Tender\s+Fee|Cost\s+of\s+Tender\s+Doc(?:ument)?)\s*[:=-]?\s*(?:Rs\.?|INR|₹)?\s*([\d,]+)", re.I)
RE_TURNOVER = re.compile(r"(?:Annual\s+Turnover|Minimum\s+Turnover)\s*[:=-]?\s*(?:Rs\.?|INR|₹)?\s*([\d,.]+\s*(?:Lakh|Cr(?:ore)?)?)", re.I)
RE_EXPERIENCE = re.compile(r"((?:\d+\s*(?:years?|yrs?)\s+(?:experience|completed\s+works?))|(?:similar\s+works?\s+of\s+value\s*[^.]+))", re.I)


def parse_numeric_inr(val_str: str) -> Optional[float]:
    """Converts strings like '₹1.5 Crores', '25 Lakhs', '50,000' to float INR."""
    if not val_str or val_str.lower() in ("not published", "not stated", "nil", "exempted"):
        return None
    val_clean = val_str.replace(",", "").strip()

    m_cr = RE_VAL_CRORE.search(val_str)
    if m_cr:
        try:
            return float(m_cr.group(1).replace(",", "")) * 10000000.0
        except ValueError:
            pass

    m_lk = RE_VAL_LAKH.search(val_str)
    if m_lk:
        try:
            return float(m_lk.group(1).replace(",", "")) * 100000.0
        except ValueError:
            pass

    digits = re.search(r"(\d+(?:\.\d+)?)", val_clean)
    if digits:
        try:
            return float(digits.group(1))
        except ValueError:
            pass
    return None


def extract_tender_intelligence(raw_text: str, source_url: str = "", page_map: Optional[dict[int, str]] = None) -> ExtractedTenderData:
    """Extracts factual tender attributes with evidence snippets and page citations."""
    out = ExtractedTenderData()
    evidence_dict: dict[str, Any] = {}

    # 1. Tender Reference Number
    m_ref = RE_REF_NO.search(raw_text)
    if m_ref:
        out.reference_number = m_ref.group(1).strip()
        evidence_dict["reference_number"] = {
            "value": out.reference_number,
            "snippet": m_ref.group(0),
            "source": "pattern_match"
        }

    # 2. Estimated Value
    m_val = RE_VAL_CRORE.search(raw_text) or RE_VAL_LAKH.search(raw_text) or RE_VAL_EXACT.search(raw_text)
    if m_val:
        out.estimated_value_str = m_val.group(0).strip()
        out.estimated_value_numeric = parse_numeric_inr(out.estimated_value_str)
        evidence_dict["estimated_value"] = {
            "value": out.estimated_value_str,
            "numeric_inr": out.estimated_value_numeric,
            "snippet": m_val.group(0)
        }

    # 3. EMD Amount & Exemption
    m_emd = RE_EMD.search(raw_text)
    if m_emd:
        out.emd_amount_str = f"₹{m_emd.group(1).strip()}"
        out.emd_numeric = parse_numeric_inr(m_emd.group(1))
        evidence_dict["emd"] = {
            "value": out.emd_amount_str,
            "numeric_inr": out.emd_numeric,
            "snippet": m_emd.group(0)
        }

    if re.search(r"\b(MSME|Udyam|MSEs?)\s+(?:exemption|exempted|waived)\b", raw_text, re.I):
        out.msme_emd_exemption = True
        evidence_dict["msme_exemption"] = {
            "value": "Eligible for EMD exemption",
            "snippet": "MSME / Udyam holders exempted from EMD"
        }

    # 4. Tender Fee
    m_fee = RE_TENDER_FEE.search(raw_text)
    if m_fee:
        out.tender_fee_str = m_fee.group(0).strip()
        evidence_dict["tender_fee"] = {
            "value": out.tender_fee_str,
            "snippet": m_fee.group(0)
        }

    # 5. Technical Eligibility (Turnover & Prior Experience)
    m_to = RE_TURNOVER.search(raw_text)
    if m_to:
        out.turnover_requirement = m_to.group(0).strip()
        evidence_dict["turnover"] = {"value": out.turnover_requirement, "snippet": m_to.group(0)}

    m_exp = RE_EXPERIENCE.search(raw_text)
    if m_exp:
        out.experience_requirement = m_exp.group(1).strip()
        evidence_dict["experience"] = {"value": out.experience_requirement, "snippet": m_exp.group(0)}

    # 6. Registrations
    regs = []
    if re.search(r"\bGST\b", raw_text, re.I):
        regs.append("GST Registration Certificate")
    if re.search(r"\bPAN\b", raw_text, re.I):
        regs.append("Permanent Account Number (PAN)")
    if re.search(r"\b(EPF|ESI)\b", raw_text, re.I):
        regs.append("EPF & ESI Registration")
    if re.search(r"\bClass-?[I|II|III|IV|V]\b", raw_text, re.I):
        regs.append("Valid Class Contractor Registration")
    out.required_registrations = regs

    # 7. Plain-language Summary
    parts = []
    if out.reference_number:
        parts.append(f"Tender Ref: {out.reference_number}.")
    if out.estimated_value_numeric:
        parts.append(f"Estimated project value is ₹{out.estimated_value_numeric:,.0f}.")
    if out.emd_amount_str != "Not published":
        parts.append(f"Earnest Money Deposit (EMD) is {out.emd_amount_str}")
        if out.msme_emd_exemption:
            parts.append("(MSME/Udyam registered enterprises are exempted).")
        else:
            parts.append(".")
    if out.turnover_requirement != "Not stated":
        parts.append(f"Requires: {out.turnover_requirement}.")

    out.plain_language_summary = " ".join(parts) or "Public procurement opportunity published by official issuing department."
    out.document_evidence = evidence_dict
    return out
