"""AGENT 03 - TENDER SCOUT: Discovers, extracts, classifies, and monitors government & PSU procurement tenders.

Supported real-world sources:
* gem_public_bids - Government e-Marketplace (GeM) public bids (JSON search interface + official Bid PDF + HTML card parser)
* cppp_eprocure   - Central Public Procurement Portal (eprocure.gov.in) active tenders, full detail views & corrigendums
* sidbi_tenders   - SIDBI institutional procurement RFPs & empanelment notices (Playwright browser)

Never invents missing values: explicitly uses 'Not published' or 'Not stated'.
Never submits bids or registers vendor accounts.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from urllib.parse import urljoin

from app.agents.base import AgentConfig, BaseAgent, ScanContext
from app.enums import BECCISector, GeographicLevel, TenderStatus
from app.fetch.http_fetcher import BlockedError, FetchError
from app.models import Source
from app.pipeline.extraction import (
    Claim,
    ExtractedItem,
    clean_text,
    parse_date,
    pdf_text,
    snippet_around,
    soup_of,
    visible_text,
)
from app.security.urls import safe_link

NOT_PUBLISHED = "Not published"
NOT_STATED = "Not stated"
NOT_VERIFIED = "Not verified"

# --------------------------------------------------------------------------- 1. BECCI 11-Sector Classification
SECTOR_RULES: list[tuple[BECCISector, re.Pattern]] = [
    (
        BECCISector.HEALTHCARE,
        re.compile(
            r"\b(medical|hospital|surgical|laparoscopic|laproscopic|cholangioscopy|ultrasound|health|"
            r"pharmaceutical|medicine|diagnostic|ambulance|clinical|dental| orthopaedic|pathology|x-ray)\b",
            re.I,
        ),
    ),
    (
        BECCISector.IT_TECHNOLOGY,
        re.compile(
            r"\b(software|hardware|servers?|networks?|data\s+aggregator|cctv|anpr|cameras?|nvr|computers?|laptops?|"
            r"telecom|cloud|cyber\s*security|cyber|gis|it\s+systems?|cohesity|fiber\s+network|interactive\s+displays?|"
            r"display\s+screens?|digital|erp|m365|microsoft\s+365|software\s+licens\w*|subscription\s+of\s+m365|"
            r"technology\s+refresh|security\s+solutions?|information\s+security|"
            r"radar\s+vfr\s+3d\s+tower\s+simulator)\b",
            re.I,
        ),
    ),

    (
        BECCISector.CONSTRUCTION_INFRASTRUCTURE,
        re.compile(
            r"\b(civil\s+works?|road|highway|nh-\d+|slope\s+protection|building|bridge|godown|boundary\s+wall|"
            r"renovation|construction|watch\s+tower|morcha|pavement|water\s+supply|sewerage|drainage|earthwork|"
            r"soil\s+investigation|covered\s+shed|structural|metro|railway\s+track)\b",
            re.I,
        ),
    ),
    (
        BECCISector.EDUCATION_TRAINING,
        re.compile(
            r"\b(education|training|skill\s+development|school|university|college|classroom|simulator\s+system|"
            r"library|academic|hostel|institute|learning)\b",
            re.I,
        ),
    ),
    (
        BECCISector.AGRICULTURE_ALLIED,
        re.compile(
            r"\b(agriculture|agricultural|irrigation|dairy|fisheries|fertilizer|seed|horticulture|veterinary|"
            r"forestry|crop|tractor|farm|agro)\b",
            re.I,
        ),
    ),
    (
        BECCISector.FINANCE_PROFESSIONAL,
        re.compile(
            r"\b(consultancy|consultant|audit|auditor|legal|financial|insurance|valuation|implementing\s+agenc|"
            r"due\s+diligence|project\s+management\s+unit|pmu|advisory|chartered\s+accountant|tax)\b",
            re.I,
        ),
    ),
    (
        BECCISector.HOSPITALITY_TOURISM,
        re.compile(
            r"\b(catering|canteen|hotel|hospitality|tourism|event\s+management|guest\s+house|food\s+service|"
            r"housekeeping\s+and\s+catering|travel)\b",
            re.I,
        ),
    ),
    (
        BECCISector.MANUFACTURING,
        re.compile(
            r"\b(manufacturing|machinery|luminaire|led\s+luminaire|bollard|hydrochloric\s+acid|chemical|"
            r"wheel\s*&\s*tyre|fabrication|transformer|generator|turbine|boiler|pump|valve|cable|ups\s+wiring|"
            r"energy-efficient|renewable\s+energy|solar|plant|equipment)\b",
            re.I,
        ),
    ),
    (
        BECCISector.TRADING_DISTRIBUTION,
        re.compile(
            r"\b(waste\s+container|dustbin|furniture|almirah|chair|stationery|paper|office\s+supplies|"
            r"consumables|garment|uniform|footwear|utensil|supply\s+of|miscellaneous\s+goods)\b",
            re.I,
        ),
    ),
    (
        BECCISector.SERVICES,
        re.compile(
            r"\b(security\s+agency|manpower|housekeeping|maintenance|amc|cmc|repair|hiring\s+of|cleaning|"
            r"mining|mine\s+development|periodical\s+services|inspection|testing|operation\s+and\s+maintenance|"
            r"custom\s+bid\s+for\s+services)\b",
            re.I,
        ),
    ),
]


def classify_sector(
    text: str,
    product_category: str = "",
    tender_category: str = "",
    *,
    title: str = "",
    buyer_text: str = "",
) -> str:
    """Classifies a tender into one of the 11 BECCI sectors with strict context precedence:
    1. Product category
    2. Tender title
    3. Relevant technical description
    4. Buyer or ministry information
    5. Tender category fallback
    """
    tiers = []
    if product_category and product_category.strip().lower() not in ("", "not stated", "na", "n/a"):
        tiers.append(product_category)
    if title and title.strip():
        tiers.append(title)
    if text and text.strip():
        tiers.append(title_or_text(text))
    if buyer_text and buyer_text.strip():
        tiers.append(buyer_text)

    for tier_text in tiers:
        for sector, pattern in SECTOR_RULES:
            if pattern.search(tier_text):
                return sector.value

    if "work" in tender_category.lower():
        return BECCISector.CONSTRUCTION_INFRASTRUCTURE.value
    if "service" in tender_category.lower():
        return BECCISector.SERVICES.value
    if "good" in tender_category.lower() or "product" in tender_category.lower():
        return BECCISector.TRADING_DISTRIBUTION.value
    return BECCISector.OTHER.value



def title_or_text(s: str) -> str:
    return (s or "")[:1500]


# --------------------------------------------------------------------------- 2. Geographic Classification
INDIAN_STATES: dict[str, re.Pattern] = {
    "Telangana": re.compile(r"\b(telangana|hyderabad|secunderabad|warangal|karimnagar|khammam|nizamabad|nagarjuna\s*sagar)\b", re.I),
    "Maharashtra": re.compile(r"\b(maharashtra|mumbai|navi\s+mumbai|pune|nagpur|kamptee|nashik|thane|aurangabad|raigad|konkan|varandh\s+ghat|mcgm|pwd-pen)\b", re.I),
    "Andhra Pradesh": re.compile(r"\b(andhra\s+pradesh|visakhapatnam|vijayawada|guntur|tirupati|amaravati|kurnool|nellore)\b", re.I),
    "Gujarat": re.compile(r"\b(gujarat|ahmedabad|gandhinagar|surat|vadodara|rajkot)\b", re.I),
    "Karnataka": re.compile(r"\b(karnataka|bengaluru|bangalore|mysuru|hubballi|mangaluru)\b", re.I),
    "Tamil Nadu": re.compile(r"\b(tamil\s+nadu|chennai|anna\s+road|coimbatore|madurai|tiruchirappalli)\b", re.I),
    "Uttar Pradesh": re.compile(r"\b(uttar\s+pradesh|lucknow|kanpur|varanasi|noida|agra|prayagraj|aligarh|amu\s+campus)\b", re.I),
    "Madhya Pradesh": re.compile(r"\b(madhya\s+pradesh|bhopal|indore|gwalior|jabalpur|neemuch|raisen)\b", re.I),
    "Delhi": re.compile(r"\b(new\s+delhi|delhi|ncr)\b", re.I),
    "West Bengal": re.compile(r"\b(west\s+bengal|kolkata|howrah|durgapur)\b", re.I),
    "Rajasthan": re.compile(r"\b(rajasthan|jaipur|jodhpur|udaipur|kota)\b", re.I),
    "Kerala": re.compile(r"\b(kerala|thiruvananthapuram|kochi|kozhikode)\b", re.I),
    "Odisha": re.compile(r"\b(odisha|bhubaneswar|cuttack|rourkela)\b", re.I),
    "Assam": re.compile(r"\b(assam|guwahati|dibrugarh)\b", re.I),
    "Bihar": re.compile(r"\b(bihar|patna|gaya)\b", re.I),
    "Punjab": re.compile(r"\b(punjab|chandigarh|ludhiana|amritsar)\b", re.I),
    "Haryana": re.compile(r"\b(haryana|gurugram|faridabad|ambala)\b", re.I),
    "Chhattisgarh": re.compile(r"\b(chhattisgarh|raipur|bilaspur)\b", re.I),
    "Jharkhand": re.compile(r"\b(jharkhand|ranchi|jamshedpur|dhanbad)\b", re.I),
}

CITY_LOOKUP: dict[str, tuple[str, str]] = {
    "hyderabad": ("Telangana", "Hyderabad"),
    "nagarjuna sagar": ("Telangana", "Nagarjuna Sagar"),
    "warangal": ("Telangana", "Warangal"),
    "karimnagar": ("Telangana", "Karimnagar"),
    "khammam": ("Telangana", "Khammam"),
    "visakhapatnam": ("Andhra Pradesh", "Visakhapatnam"),
    "vijayawada": ("Andhra Pradesh", "Vijayawada"),
    "amaravati": ("Andhra Pradesh", "Amaravati"),
    "guntur": ("Andhra Pradesh", "Guntur"),
    "tirupati": ("Andhra Pradesh", "Tirupati"),
    "kurnool": ("Andhra Pradesh", "Kurnool"),
    "nellore": ("Andhra Pradesh", "Nellore"),
    "rajahmundry": ("Andhra Pradesh", "Rajahmundry"),
    "kakinada": ("Andhra Pradesh", "Kakinada"),
    "anantapur": ("Andhra Pradesh", "Anantapur"),
    "mumbai": ("Maharashtra", "Mumbai"),
    "navi mumbai": ("Maharashtra", "Navi Mumbai"),
    "pune": ("Maharashtra", "Pune"),
    "nagpur": ("Maharashtra", "Nagpur"),
    "kamptee": ("Maharashtra", "Kamptee"),
    "pen": ("Maharashtra", "Pen"),
    "chennai": ("Tamil Nadu", "Chennai"),
    "lucknow": ("Uttar Pradesh", "Lucknow"),
    "aligarh": ("Uttar Pradesh", "Aligarh"),
    "neemuch": ("Madhya Pradesh", "Neemuch"),
    "ahmedabad": ("Gujarat", "Ahmedabad"),
    "gandhinagar": ("Gujarat", "Gandhinagar"),
    "bengaluru": ("Karnataka", "Bengaluru"),
    "new delhi": ("Delhi", "New Delhi"),
}


def classify_geography(text: str, explicit_location: str = "", org_chain: str = "") -> tuple[str | None, str | None, str]:
    """Returns (state, city, location_type). Only assigns state/city when supported by source text."""
    combined = f"{explicit_location} {text} {org_chain}"
    low = combined.lower()

    detected_state: str | None = None
    detected_city: str | None = None

    for city_key, (st, city_name) in CITY_LOOKUP.items():
        if re.search(rf"\b{re.escape(city_key)}\b", low):
            detected_state = st
            detected_city = city_name
            break

    if not detected_state:
        for st, pat in INDIAN_STATES.items():
            if pat.search(combined):
                detected_state = st
                break

    if explicit_location and explicit_location.upper() not in ("NA", "NOT PUBLISHED", "NOT STATED", "INDIA"):
        if not detected_city and len(explicit_location) <= 40:
            detected_city = explicit_location.title()

    if detected_city:
        loc_type = GeographicLevel.LOCAL.value if any(
            k in low for k in ["campus", "branch", "ward", "village", "mcgm", "ghat", "sagar"]
        ) else GeographicLevel.DISTRICT.value
    elif detected_state:
        loc_type = GeographicLevel.STATE.value
    else:
        loc_type = GeographicLevel.NATIONAL.value

    return detected_state, detected_city, loc_type


# --------------------------------------------------------------------------- 3. Eligibility Intelligence
def extract_eligibility_intelligence(text: str, fields: dict | None = None) -> dict:
    """Extracts structured eligibility intelligence without making unsupported personal eligibility claims."""
    fields = fields or {}
    t = text or ""

    # 1. MSME / MSE preference & exemption
    msme_m = re.search(
        r"(MSE\s+Relaxation\s+for\s+Years\s+Of\s+Experience\s+and\s+Turnover\s*:?\s*(Yes|No)[^\n.]*|"
        r"Purchase\s+preference\s+to\s+Micro\s+and\s+Small\s+Enterprises\s*\(MSEs\)[^.\n]+|"
        r"Under\s+MSE\s+category,[^.\n]+eligible\s+for\s+exemption\s+from\s+EMD|"
        r"EMD\s+Exemption\s+Allowed\s*:?\s*(Yes|No))",
        t,
        re.I,
    )
    msme_val = fields.get("msme_preference") or (clean_text(msme_m.group(0)) if msme_m else NOT_STATED)

    # 2. Udyam Registration
    udyam_m = re.search(r"([^.\n]*\bUdyam\s+(?:Certificate|Registration)[^.\n]*)", t, re.I)
    udyam_val = clean_text(udyam_m.group(1)) if udyam_m else (
        "Valid Udyam Registration required for MSE benefits" if "mse" in msme_val.lower() and "yes" in msme_val.lower() else NOT_STATED
    )

    # 3. GST Requirement
    gst_m = re.search(r"([^.\n]*\bGST(?:IN)?\b[^.\n]{0,120})", t, re.I)
    gst_val = clean_text(gst_m.group(1)) if gst_m else NOT_STATED

    # 4. PAN Requirement
    pan_m = re.search(r"([^.\n]*\bPAN\s+(?:Card|Number|Registration)\b[^.\n]{0,100})", t, re.I)
    pan_val = clean_text(pan_m.group(1)) if pan_m else NOT_STATED

    # 5. Turnover Condition
    turn_val = fields.get("turnover_requirement") or NOT_STATED
    if turn_val == NOT_STATED:
        turn_m = re.search(
            r"(?:Minimum\s+Average\s+Annual\s+Turnover[^.\n]*?(\d+[\d,.]*\s*(?:Lakh|Crore|INR|Rs\.?)\s*\(?s?\)?)|"
            r"average\s+annual\s+financial\s+turnover[^.\n]{0,120})",
            t,
            re.I,
        )
        if turn_m:
            turn_val = clean_text(turn_m.group(0))

    # 6. Experience Condition
    exp_val = fields.get("experience_requirement") or NOT_STATED
    if exp_val == NOT_STATED:
        exp_m = re.search(
            r"(?:Years\s+of\s+Past\s+Experience\s+Required[^.\n]*?(\d+\s*Year\s*\(?s?\)?)|"
            r"Three\s+similar\s+completed\s+services\s+costing\s+not\s+less\s+than\s+the\s+amount\s+equal\s+to\s+40%[^.\n]*)",
            t,
            re.I,
        )
        if exp_m:
            exp_val = clean_text(exp_m.group(0))

    # 7. Company / OEM / Seller Type
    comp_m = re.search(
        r"(bidder\s+must\s+be\s+the\s+manufacturer\s*/\s*OEM[^.\n]*|Traders\s+are\s+excluded[^.\n]*|"
        r"Service\s+provider\s+of\s+the\s+offered\s+Service[^.\n]*)",
        t,
        re.I,
    )

    comp_val = clean_text(comp_m.group(0)) if comp_m else NOT_STATED

    # 8. Licences / Certificates
    lic_m = re.search(r"(?:Document\s+required\s+from\s+seller|NDA/Pre\s+Qualification)\s*:?\s*([^\n.]{5,160})", t, re.I)
    lic_val = clean_text(lic_m.group(1)) if lic_m else NOT_STATED

    # 9. Consortium / Joint Venture
    jv_m = re.search(r"([^.\n]*\b(?:Consortium|Joint\s+Venture|\bJV\b)[^.\n]{0,100})", t, re.I)
    jv_val = clean_text(jv_m.group(1)) if jv_m else NOT_STATED

    registrations: list[str] = []
    if udyam_val != NOT_STATED:
        registrations.append("Udyam Registration (for MSE benefits)")
    if gst_val != NOT_STATED:
        registrations.append("GST Registration")
    if pan_val != NOT_STATED:
        registrations.append("PAN")
    if "bharat kosh" in t.lower():
        registrations.append("BharatKosh Fee Receipt")
    if "power of attorney" in t.lower():
        registrations.append("Power of Attorney / Bid Security")
    if "oem" in comp_val.lower():
        registrations.append("Manufacturer / OEM Authorization")

    # Ambiguous flag: if pre-qualification says "As per Tender Document" or "As per ATC" without explicit turnover/experience
    ambiguous = bool(
        (turn_val == NOT_STATED and exp_val == NOT_STATED)
        or re.search(r"\b(as\s+per\s+atc|as\s+per\s+tender\s+document)\b", t, re.I)
    )

    return {
        "msme_eligibility": msme_val,
        "udyam_registration": udyam_val,
        "gst_requirement": gst_val,
        "pan_requirement": pan_val,
        "company_registration": comp_val,
        "industry_licences": lic_val,
        "experience_conditions": exp_val,
        "turnover_conditions": turn_val,
        "bidder_turnover_conditions": fields.get("bidder_turnover_requirement")
        or (turn_val if fields.get("turnover_field_variant") == "bidder_average_annual_turnover" else NOT_STATED),
        "oem_turnover_conditions": fields.get("oem_turnover_requirement") or NOT_STATED,
        "turnover_field_variant": fields.get("turnover_field_variant")
        or ("text_extracted_bidder_turnover" if turn_val != NOT_STATED else None),
        "category_conditions": comp_val if comp_val != NOT_STATED else NOT_STATED,
        "consortium_jv_permissions": jv_val,
        "required_registrations": registrations,
        "ambiguous_flag": ambiguous,
    }


# --------------------------------------------------------------------------- 4. Deadline Status Evaluation
def evaluate_tender_status(
    deadline: dt.date | None,
    opening_date: dt.date | None = None,
    *,
    is_cancelled: bool = False,
    is_extended: bool = False,
    today: dt.date | None = None,
) -> str:
    today = today or dt.date.today()
    if is_cancelled:
        return TenderStatus.CANCELLED.value
    if not deadline:
        return TenderStatus.UNDER_VERIFICATION.value
    if deadline < today:
        return TenderStatus.EXPIRED.value
    if is_extended:
        return TenderStatus.EXTENDED.value
    if opening_date and opening_date > today and deadline > today:
        # Bid submission hasn't opened yet
        if (opening_date - today).days > 0 and opening_date <= deadline:
            return TenderStatus.UPCOMING.value
    days_left = (deadline - today).days
    if days_left <= 7:
        return TenderStatus.CLOSING_SOON.value
    return TenderStatus.OPEN.value


# --------------------------------------------------------------------------- 5. GeM Public Bids Parser
def parse_gem_pdf_details(pdf_str: str) -> tuple[dict, list[Claim]]:
    """Extracts structured procurement fields and evidence snippets from an official GeM Bid Document PDF."""
    fields: dict = {}
    claims: list[Claim] = []
    if not pdf_str:
        return fields, claims

    # Dated / Published Date
    m_pub = re.search(r"Dated\s*:\s*(\d{2}-\d{2}-\d{4})", pdf_str, re.I)
    if m_pub and parse_date(m_pub.group(1)):
        d_iso = parse_date(m_pub.group(1)).isoformat()
        fields["published_date"] = d_iso
        claims.append(Claim("published_date", d_iso, snippet_around(pdf_str, m_pub.start(), m_pub.end())))

    # Bid End Date/Time
    m_end = re.search(r"Bid\s+End\s+Date/Time\s*(\d{2}-\d{2}-\d{4})", pdf_str, re.I)
    if m_end and parse_date(m_end.group(1)):
        d_iso = parse_date(m_end.group(1)).isoformat()
        fields["pdf_deadline"] = d_iso

    # Bid Opening Date/Time
    m_open = re.search(r"Bid\s+Opening\s+Date/Time\s*(\d{2}-\d{2}-\d{4})", pdf_str, re.I)
    if m_open and parse_date(m_open.group(1)):
        d_iso = parse_date(m_open.group(1)).isoformat()
        fields["bid_opening_date"] = d_iso
        claims.append(Claim("bid_opening_date", d_iso, snippet_around(pdf_str, m_open.start(), m_open.end())))

    # Organisation Name (guarding against placeholder 'N/a' or masked values)
    m_org = re.search(
        r"Organisation\s+Name(?:\s*/\s*[^\s]+)?\s+([A-Za-z0-9 &(),.\-/]+?)(?:\s+Office\s+Name|\s+काया|\s+Contact\s+details|\s+Ministry/State)",
        pdf_str,
        re.I,
    )
    if m_org:
        org_val = clean_text(m_org.group(1))
        if (
            org_val
            and "*" not in org_val
            and org_val.lower().strip(" ./-") not in ("", "n/a", "na", "n.a", "nil", "none", "not applicable")
        ):
            fields["organisation_name"] = org_val
            claims.append(Claim("issuing_organisation", org_val, snippet_around(pdf_str, m_org.start(), m_org.end())))

    # Estimated Bid Value in INR
    m_val = re.search(r"Estimated\s+Bid\s+Value\s+in\s+INR[^0-9]{0,40}(\d[\d,]*)", pdf_str, re.I)
    if m_val:
        val_fmt = f"INR {m_val.group(1)}"
        fields["estimated_value"] = val_fmt
        claims.append(Claim("estimated_value", val_fmt, snippet_around(pdf_str, m_val.start(), m_val.end())))

    # EMD Amount
    m_emd = re.search(r"EMD\s+Amount\s+(\d[\d,]*)", pdf_str, re.I)
    if m_emd:
        emd_fmt = f"INR {m_emd.group(1)}"
        fields["emd_amount"] = emd_fmt
        claims.append(Claim("emd_amount", emd_fmt, snippet_around(pdf_str, m_emd.start(), m_emd.end())))
    elif re.search(r"EMD\s+Detail\s+Required\s+No", pdf_str, re.I):
        fields["emd_amount"] = "INR 0 (Not required)"

    # Turnover Variants: Bidder Average Annual Turnover vs OEM Average Turnover (Last 3 Years)
    m_bidder_turn = re.search(
        r"Minimum\s+Average\s+Annual\s+Turnover\s+of\s+the\s+bidder\s*\([^)]+\)\s*(\d+[\d,.]*\s*(?:Lakh|Crore)\s*\(?s?\)?)",
        pdf_str,
        re.I,
    )
    m_oem_turn = re.search(
        r"OEM\s+Average\s+Turnover\s*\(Last\s*3\s*Years\)\s*(\d+[\d,.]*\s*(?:Lakh|Crore)\s*\(?s?\)?)",
        pdf_str,
        re.I,
    )
    bidder_turn_val = clean_text(m_bidder_turn.group(1)) if m_bidder_turn else None
    oem_turn_val = clean_text(m_oem_turn.group(1)) if m_oem_turn else None

    if bidder_turn_val and oem_turn_val:
        fields["bidder_turnover_requirement"] = bidder_turn_val
        fields["oem_turnover_requirement"] = oem_turn_val
        fields["turnover_field_variant"] = "both_bidder_and_oem_turnover"
        fields["turnover_requirement"] = (
            f"Bidder Turnover: {bidder_turn_val}; OEM Average Turnover (Last 3 Years): {oem_turn_val}"
        )
        claims.append(
            Claim("turnover_requirement", bidder_turn_val, snippet_around(pdf_str, m_bidder_turn.start(), m_bidder_turn.end()))
        )
        claims.append(
            Claim("oem_turnover_requirement", oem_turn_val, snippet_around(pdf_str, m_oem_turn.start(), m_oem_turn.end()))
        )
    elif bidder_turn_val:
        fields["bidder_turnover_requirement"] = bidder_turn_val
        fields["turnover_field_variant"] = "bidder_average_annual_turnover"
        fields["turnover_requirement"] = bidder_turn_val
        claims.append(
            Claim("turnover_requirement", bidder_turn_val, snippet_around(pdf_str, m_bidder_turn.start(), m_bidder_turn.end()))
        )
    elif oem_turn_val:
        fields["oem_turnover_requirement"] = oem_turn_val
        fields["turnover_field_variant"] = "oem_average_turnover_3yr"
        fields["turnover_requirement"] = f"OEM Average Turnover (Last 3 Years): {oem_turn_val}"
        claims.append(
            Claim(
                "oem_turnover_requirement",
                f"OEM Average Turnover (Last 3 Years): {oem_turn_val}",
                snippet_around(pdf_str, m_oem_turn.start(), m_oem_turn.end()),
            )
        )

    # Years of Past Experience
    m_exp = re.search(
        r"Years\s+of\s+Past\s+Experience\s+Required\s+for\s+same/similar\s+service\s*(\d+\s*Year\s*\(?s?\)?)",
        pdf_str,
        re.I,
    )
    if m_exp:
        e_val = clean_text(m_exp.group(1))
        fields["experience_requirement"] = e_val
        claims.append(Claim("experience", e_val, snippet_around(pdf_str, m_exp.start(), m_exp.end())))

    # MSE Relaxation / Purchase Preference
    mse_parts = []
    m_mse_rel = re.search(
        r"MSE\s+Relaxation\s+for\s+Years\s+Of\s+Experience\s+and\s+Turnover\s*(Yes\s*\|\s*Complete|Yes|No)",
        pdf_str,
        re.I,
    )
    if m_mse_rel:
        mse_parts.append(f"MSE Relaxation (Experience & Turnover): {clean_text(m_mse_rel.group(1))}")
        claims.append(
            Claim("msme_preference", mse_parts[-1], snippet_around(pdf_str, m_mse_rel.start(), m_mse_rel.end()))
        )
    if re.search(r"Purchase\s+preference\s+to\s+Micro\s+and\s+Small\s+Enterprises\s*\(MSEs\)", pdf_str, re.I):
        mse_parts.append("MSE Purchase Preference (L-1 + 15%) applicable with valid Udyam Certificate")
    if re.search(r"Under\s+MSE\s+category,\s+only\s+manufacturers.*eligible\s+for\s+exemption\s+from\s+EMD", pdf_str, re.I):
        mse_parts.append("EMD Exemption available for MSE manufacturers/service providers")
    if mse_parts:
        fields["msme_preference"] = "; ".join(mse_parts)

    return fields, claims


def build_gem_item_from_doc(doc: dict, pdf_str: str = "", base_url: str = "https://bidplus.gem.gov.in") -> ExtractedItem:
    first = lambda k, default="": (doc.get(k)[0] if isinstance(doc.get(k), list) and doc.get(k) else doc.get(k) or default)
    b_id = str(first("b_id", first("id", "")))
    bid_no = str(first("b_bid_number", "")).strip()
    b_type = int(first("b_bid_type", 1) or 1)
    cat_name = clean_text(str(first("bd_category_name", first("b_category_name", ""))))
    qty = str(first("b_total_quantity", ""))
    min_name = clean_text(str(first("ba_official_details_minName", "")))
    dept_name = clean_text(str(first("ba_official_details_deptName", "")))

    start_iso_raw = str(first("final_start_date_sort", ""))
    end_iso_raw = str(first("final_end_date_sort", ""))
    start_d = parse_date(start_iso_raw[:10]) if start_iso_raw else None
    end_d = parse_date(end_iso_raw[:10]) if end_iso_raw else None

    doc_path = "showradocumentPdf" if b_type == 2 else "showbidDocument"
    doc_url = f"{base_url.rstrip('/')}/{doc_path}/{b_id}"

    issuing_auth = min_name or dept_name or "Government e-Marketplace (GeM)"
    department = dept_name or min_name or NOT_STATED
    title = f"GeM Bid {bid_no}: {cat_name[:180]}" if cat_name else f"GeM Procurement Bid {bid_no}"

    fields: dict = {
        "tender_id": bid_no,
        "reference_number": bid_no,
        "issuing_organisation": issuing_auth,
        "department": department,
        "tender_category": "Services" if "service" in cat_name.lower() else "Goods",
        "product_category": cat_name or NOT_STATED,
        "estimated_value": NOT_PUBLISHED,
        "emd_amount": NOT_PUBLISHED,
        "tender_fee": "INR 0 (No GeM tender document fee)",
        "turnover_requirement": NOT_STATED,
        "experience_requirement": NOT_STATED,
        "msme_preference": NOT_STATED,
        "pre_bid_details": NOT_PUBLISHED,
        "application_method": "Online submission through Government e-Marketplace (GeM) portal (bidplus.gem.gov.in)",
    }
    if start_d:
        fields["published_date"] = start_d.isoformat()
        fields["opening_date"] = start_d.isoformat()
    if end_d:
        fields["deadline"] = end_d.isoformat()
    if qty:
        fields["positions"] = f"Quantity: {qty}"

    claims: list[Claim] = [
        Claim("title", title, f"Bid No.: {bid_no} | Items: {cat_name}"),
        Claim("reference_number", bid_no, f"Bid No.: {bid_no}"),
        Claim("issuing_organisation", issuing_auth, f"Ministry: {min_name} | Department: {dept_name}"),
    ]
    if end_d:
        claims.append(Claim("deadline", end_d.isoformat(), f"End Date: {end_iso_raw}"))

    pdf_fields, pdf_claims = parse_gem_pdf_details(pdf_str)
    for k, v in pdf_fields.items():
        if k == "pdf_deadline":
            continue
        if v:
            fields[k] = v
    claims.extend(pdf_claims)

    is_extended = bool(
        pdf_fields.get("pdf_deadline")
        and fields.get("deadline")
        and pdf_fields["pdf_deadline"] < fields["deadline"]
    )

    raw_text = (
        f"Bid No: {bid_no} | Category: {cat_name} | Quantity: {qty} | "
        f"Ministry: {min_name} | Department: {dept_name} | "
        f"Start: {start_iso_raw} | End: {end_iso_raw}"
    )
    if pdf_str:
        raw_text += f"\n\n[GeM Bid Document PDF Excerpt]\n{pdf_str[:6000]}"

    technical_desc = f"Bid No: {bid_no} | Category: {cat_name} | Quantity: {qty}"
    if pdf_str:
        technical_desc += f"\n{pdf_str[:6000]}"

    sector = classify_sector(
        technical_desc,
        product_category=cat_name,
        tender_category=fields["tender_category"],
        title=title,
        buyer_text=f"{min_name} {dept_name}",
    )
    state, city, loc_type = classify_geography(raw_text, org_chain=f"{min_name} {dept_name}")
    elig_intel = extract_eligibility_intelligence(raw_text, fields)

    fields["industry"] = sector
    fields["sector"] = sector
    fields["state"] = state
    fields["city"] = city
    fields["location_type"] = loc_type
    fields["eligibility_intelligence"] = elig_intel
    fields["required_registrations"] = elig_intel["required_registrations"]
    fields["eligibility"] = (
        f"Turnover: {elig_intel['turnover_conditions']}; "
        f"Experience: {elig_intel['experience_conditions']}; "
        f"MSME Preference: {elig_intel['msme_eligibility']}"
    )
    fields["experience"] = elig_intel["experience_conditions"]
    fields["financial_details"] = (
        f"Estimated Value: {fields['estimated_value']}; "
        f"EMD: {fields['emd_amount']}; "
        f"Tender Fee: {fields['tender_fee']}"
    )
    fields["tender_status"] = evaluate_tender_status(
        parse_date(fields.get("deadline", "")),
        parse_date(fields.get("opening_date", "")),
        is_extended=is_extended,
    )

    return ExtractedItem(
        external_key=f"gem:{bid_no}",
        title=title,
        original_url=doc_url,
        application_url="https://bidplus.gem.gov.in/all-bids",
        raw_text=raw_text,
        fields=fields,
        claims=claims,
        documents=[{"title": f"GeM Official Bid Document ({bid_no})", "url": doc_url}],
        subcategory=fields["tender_category"].lower(),
    )


def parse_gem_html_cards(html: str, base_url: str = "https://bidplus.gem.gov.in") -> list[dict]:
    """Fallback parser that converts rendered GeM .card elements into the same doc dict format."""
    s = soup_of(html)
    docs: list[dict] = []
    for card in s.select(".card"):
        bid_a = card.select_one("a.bid_no_hover")
        if not bid_a:
            continue
        bid_no = clean_text(bid_a.get_text(" ", strip=True))
        href = bid_a.get("href", "")
        m_id = re.search(r"/(\d+)$", href)
        b_id = m_id.group(1) if m_id else bid_no

        item_a = card.select_one("a[data-content]")
        cat_name = clean_text(item_a.get("data-content") or item_a.get_text(" ", strip=True)) if item_a else ""

        card_txt = clean_text(card.get_text(" ", strip=True))
        m_qty = re.search(r"Quantity:\s*(\d+)", card_txt, re.I)
        qty = m_qty.group(1) if m_qty else "1"

        dept_col = card.select_one(".col-md-5")
        dept_lines = [
            clean_text(x)
            for x in (dept_col.stripped_strings if dept_col else [])
            if "department name" not in x.lower()
        ]
        min_name = dept_lines[0] if dept_lines else ""
        dept_name = dept_lines[1] if len(dept_lines) > 1 else min_name

        start_el = card.select_one(".start_date")
        end_el = card.select_one(".end_date")
        start_d = parse_date(start_el.get_text(strip=True)) if start_el else None
        end_d = parse_date(end_el.get_text(strip=True)) if end_el else None

        docs.append(
            {
                "b_id": [b_id],
                "b_bid_number": [bid_no],
                "b_bid_type": [1],
                "bd_category_name": [cat_name],
                "b_total_quantity": [qty],
                "ba_official_details_minName": [min_name] if min_name else [],
                "ba_official_details_deptName": [dept_name] if dept_name else [],
                "final_start_date_sort": [start_d.isoformat() if start_d else ""],
                "final_end_date_sort": [end_d.isoformat() if end_d else ""],
            }
        )
    return docs


def gem_public_bids(source: Source, ctx: ScanContext) -> list[ExtractedItem]:
    """Discovers active public bids from GeM (bidplus.gem.gov.in) and enriches from official Bid PDFs."""
    res = ctx.http.get(source.url)
    html = res.text
    ctx.capture(source.url, res.final_url, "http", res.status, visible_text(html))

    m_csrf = re.search(r"'csrf_bd_gem_nk'\s*:\s*'([a-f0-9]+)'", html)
    docs: list[dict] = []
    max_items = int(source.config.get("max_items", 6))
    max_pdfs = int(source.config.get("max_pdfs", 4))
    sort_by = source.config.get("sort", "Bid-End-Date-Latest")

    if m_csrf:
        csrf = m_csrf.group(1)
        payload = {
            "page": 1,
            "param": {"searchBid": source.config.get("search_keyword", ""), "searchType": "fullText"},
            "filter": {
                "bidStatusType": "ongoing_bids",
                "byType": "all",
                "highBidValue": "",
                "byEndDate": {"from": "", "to": ""},
                "sort": sort_by,
            },
        }
        try:
            post_res = ctx.http.post(
                "https://bidplus.gem.gov.in/all-bids-data",
                data={"payload": json.dumps(payload), "csrf_bd_gem_nk": csrf},
                headers={"X-Requested-With": "XMLHttpRequest", "Referer": res.final_url},
            )
            data = json.loads(post_res.text)
            docs = data.get("response", {}).get("response", {}).get("docs", [])
            ctx.step("gem.json_search_ok", total_found=data.get("response", {}).get("response", {}).get("numFound", 0), batch=len(docs))
        except Exception as e:
            ctx.step("gem.json_search_fallback", error=str(e)[:200])

    if not docs:
        docs = parse_gem_html_cards(html)
        if not docs:
            page = ctx.browser.render(source.url, wait_for_selector=".card")
            ctx.capture(source.url, page.final_url, "browser", page.status, visible_text(page.html))
            docs = parse_gem_html_cards(page.html)
            ctx.step("gem.browser_cards_parsed", count=len(docs))

    items: list[ExtractedItem] = []
    pdfs_fetched = 0
    for doc in docs[:max_items]:
        b_id = doc.get("b_id")[0] if isinstance(doc.get("b_id"), list) and doc.get("b_id") else doc.get("b_id")
        b_type = doc.get("b_bid_type")[0] if isinstance(doc.get("b_bid_type"), list) and doc.get("b_bid_type") else 1
        pdf_str = ""
        if b_id and int(b_type or 1) == 1 and pdfs_fetched < max_pdfs:
            pdf_url = f"https://bidplus.gem.gov.in/showbidDocument/{b_id}"
            try:
                r_pdf = ctx.http.get(pdf_url)
                pdfs_fetched += 1
                if "pdf" in r_pdf.content_type.lower() or r_pdf.body[:5] == b"%PDF-":
                    pdf_str = pdf_text(r_pdf.body, max_pages=4)
                    ctx.capture(pdf_url, r_pdf.final_url, "http", r_pdf.status, pdf_str[:100_000])
                    ctx.step("gem.pdf_parsed", bid_id=b_id, chars=len(pdf_str))
            except (FetchError, BlockedError) as ex:
                ctx.step("gem.pdf_error", bid_id=b_id, error=str(ex)[:160])

        items.append(build_gem_item_from_doc(doc, pdf_str=pdf_str))

    return items


# --------------------------------------------------------------------------- 6. CPPP eProcure Parser
def parse_cppp_home_tables(html: str, base_url: str = "https://eprocure.gov.in/eprocure/app") -> tuple[list[dict], list[dict]]:
    """Extracts (active_tenders, corrigendums) from the CPPP eProcure home page tables."""
    s = soup_of(html)
    tenders: list[dict] = []
    corrigendums: list[dict] = []
    seen_t_refs: set[str] = set()
    seen_c_refs: set[str] = set()

    for tb in s.find_all("table"):
        rows = tb.find_all("tr")
        if not (2 <= len(rows) <= 25):
            continue
        header_cells = [clean_text(c.get_text(" ", strip=True)).lower() for c in rows[0].find_all(["th", "td"])]
        if len(header_cells) != 4:
            continue

        is_tender_tb = "tender title" in header_cells[0] and "reference no" in header_cells[1]
        is_corr_tb = "corrigendum title" in header_cells[0] and "reference no" in header_cells[1]
        if not (is_tender_tb or is_corr_tb):
            continue

        for r in rows[1:]:
            tds = r.find_all("td")
            if len(tds) != 4:
                continue
            raw_title = clean_text(tds[0].get_text(" ", strip=True))
            title = re.sub(r"^\d+\.\s*", "", raw_title).strip()
            ref_no = clean_text(tds[1].get_text(" ", strip=True))
            closing_raw = clean_text(tds[2].get_text(" ", strip=True))
            opening_raw = clean_text(tds[3].get_text(" ", strip=True))
            a = tds[0].find("a", href=True)
            detail_url = safe_link(a["href"], base_url) if a else None
            if not title or not ref_no or "more..." in title.lower():
                continue

            entry = {
                "title": title,
                "reference_number": ref_no,
                "closing_raw": closing_raw,
                "opening_raw": opening_raw,
                "detail_url": detail_url,
            }
            if is_tender_tb and ref_no not in seen_t_refs:
                seen_t_refs.add(ref_no)
                tenders.append(entry)
            elif is_corr_tb and ref_no not in seen_c_refs:
                seen_c_refs.add(ref_no)
                corrigendums.append(entry)

    return tenders, corrigendums


def parse_cppp_detail_page(html: str) -> dict:
    """Extracts key-value pairs from a CPPP Tender Details page."""
    s = soup_of(html)
    kv: dict[str, str] = {}
    for tr in s.find_all("tr"):
        tds = [clean_text(c.get_text(" ", strip=True)) for c in tr.find_all(["td", "th"], recursive=False)]
        if len(tds) in (2, 4, 6):
            for i in range(0, len(tds) - 1, 2):
                k = tds[i].rstrip(" :*").strip()
                v = tds[i + 1].strip()
                if k and len(k) < 80 and v and k not in kv:
                    kv[k] = v

    docs: list[dict] = []
    for a in s.find_all("a", href=True):
        t = clean_text(a.get_text(" ", strip=True))
        if t.lower().endswith((".pdf", ".xls", ".xlsx", ".zip")) or "tendernotice" in t.lower():
            docs.append({"title": t, "url": "https://eprocure.gov.in/eprocure/app"})

    kv["_documents"] = docs  # type: ignore[assignment]
    kv["_raw_text"] = clean_text(s.get_text(" ", strip=True))
    return kv



def build_cppp_item(
    entry: dict,
    detail_kv: dict | None = None,
    corrigendums: list[dict] | None = None,
    listing_url: str = "https://eprocure.gov.in/eprocure/app",
) -> ExtractedItem:
    detail_kv = detail_kv or {}
    corrigendums = corrigendums or []

    ref_no = detail_kv.get("Tender Reference Number") or entry["reference_number"]
    tender_id = detail_kv.get("Tender ID") or ref_no
    title = detail_kv.get("Title") or entry["title"]
    work_desc = detail_kv.get("Work Description") or title

    org_chain = detail_kv.get("Organisation Chain") or ""
    org_parts = [p.strip() for p in org_chain.split("||") if p.strip()]
    issuing_auth = org_parts[0] if org_parts else "Central Public Procurement Portal (Govt of India)"
    department = " | ".join(org_parts[1:]) if len(org_parts) > 1 else (org_parts[0] if org_parts else NOT_STATED)

    t_cat = detail_kv.get("Tender Category") or NOT_STATED
    p_cat = detail_kv.get("Product Category") or NOT_STATED

    raw_val = detail_kv.get("Tender Value in ₹") or ""
    est_val = f"INR {raw_val}" if raw_val and raw_val.upper() != "NA" else NOT_PUBLISHED

    raw_emd = detail_kv.get("EMD Amount in ₹") or ""
    emd_val = f"INR {raw_emd}" if raw_emd and raw_emd.upper() != "NA" else NOT_PUBLISHED

    raw_fee = detail_kv.get("Tender Fee in ₹") or ""
    fee_val = f"INR {raw_fee}" if raw_fee and raw_fee.upper() != "NA" else NOT_PUBLISHED

    pub_raw = detail_kv.get("Published Date") or ""
    sub_start_raw = detail_kv.get("Bid Submission Start Date") or pub_raw
    dl_end_raw = detail_kv.get("Document Download / Sale End Date") or ""
    pre_bid_raw = detail_kv.get("Pre Bid Meeting Date") or ""
    sub_end_raw = detail_kv.get("Bid Submission End Date") or entry["closing_raw"]
    open_raw = detail_kv.get("Bid Opening Date") or entry["opening_raw"]

    pub_d = parse_date(pub_raw)
    sub_start_d = parse_date(sub_start_raw)
    dl_end_d = parse_date(dl_end_raw)
    pre_bid_d = parse_date(pre_bid_raw)
    deadline_d = parse_date(sub_end_raw)
    bid_open_d = parse_date(open_raw)


    pre_bid_place = detail_kv.get("Pre Bid Meeting Address") or detail_kv.get("Pre Bid Meeting Place") or NOT_PUBLISHED
    location_str = detail_kv.get("Location") or ""
    pre_qual = detail_kv.get("NDA/Pre Qualification") or NOT_STATED
    remarks = detail_kv.get("Independent External Monitor/Remarks") or ""
    emd_exempt = detail_kv.get("EMD Exemption Allowed") or ""
    fee_exempt = detail_kv.get("Tender Fee Exemption Allowed") or ""

    # Match any corrigendums for this reference number
    matching_corrs = [
        c for c in corrigendums
        if c["reference_number"].lower() == ref_no.lower() or ref_no.lower() in c["reference_number"].lower()
    ]
    is_extended = False
    is_cancelled = False
    corr_history: list[dict] = []
    for mc in matching_corrs:
        c_title = mc["title"]
        new_dl = parse_date(mc["closing_raw"])
        if re.search(r"\b(cancel\w*|withdrawn\w*|annul\w*)\b", c_title, re.I):
            is_cancelled = True

        if new_dl and (not deadline_d or new_dl >= deadline_d):
            is_extended = True
            old_iso = deadline_d.isoformat() if deadline_d else None
            deadline_d = new_dl
            corr_history.append(
                {
                    "title": c_title,
                    "reference_number": mc["reference_number"],
                    "old_deadline": old_iso,
                    "new_deadline": new_dl.isoformat(),
                }
            )

    raw_text = detail_kv.get("_raw_text") or (
        f"Title: {title} | Reference No: {ref_no} | Closing Date: {sub_end_raw} | Bid Opening Date: {open_raw}"
    )

    msme_pref = NOT_STATED
    if emd_exempt or fee_exempt:
        msme_pref = f"EMD Exemption Allowed: {emd_exempt or 'No'}; Tender Fee Exemption Allowed: {fee_exempt or 'No'}"

    fields: dict = {
        "tender_id": tender_id,
        "reference_number": ref_no,
        "issuing_organisation": issuing_auth,
        "department": department,
        "tender_category": t_cat,
        "product_category": p_cat,
        "description": work_desc,
        "estimated_value": est_val,
        "emd_amount": emd_val,
        "tender_fee": fee_val,
        "pre_bid_details": pre_bid_place if pre_bid_place != "NA" else NOT_PUBLISHED,
        "msme_preference": msme_pref,
        "corrigendum_history": corr_history,
        "cancellation_reason": "Cancelled via Corrigendum notice" if is_cancelled else None,
        "application_method": "Online submission via Central Public Procurement Portal (eprocure.gov.in)",
    }
    if pub_d:
        fields["published_date"] = pub_d.isoformat()
    if sub_start_d:
        fields["opening_date"] = sub_start_d.isoformat()
    if dl_end_d:
        fields["document_download_date"] = dl_end_d.isoformat()
    if pre_bid_d:
        fields["pre_bid_date"] = pre_bid_d.isoformat()
    if deadline_d:
        fields["deadline"] = deadline_d.isoformat()
    if bid_open_d:
        fields["bid_opening_date"] = bid_open_d.isoformat()


    sector = classify_sector(
        work_desc,
        product_category=p_cat,
        tender_category=t_cat,
        title=title,
        buyer_text=org_chain,
    )
    state, city, loc_type = classify_geography(f"{title} {work_desc}", explicit_location=location_str, org_chain=org_chain)
    elig_intel = extract_eligibility_intelligence(f"{pre_qual} {remarks} {raw_text}", fields)

    fields["industry"] = sector
    fields["sector"] = sector
    fields["state"] = state
    fields["city"] = city
    fields["location_type"] = loc_type
    fields["eligibility_intelligence"] = elig_intel
    fields["required_registrations"] = elig_intel["required_registrations"]
    fields["turnover_requirement"] = elig_intel["turnover_conditions"]
    fields["experience_requirement"] = elig_intel["experience_conditions"]
    fields["experience"] = elig_intel["experience_conditions"]
    fields["eligibility"] = (
        f"Pre-Qualification: {pre_qual}" if pre_qual not in ("NA", NOT_STATED)
        else f"Registrations: {', '.join(elig_intel['required_registrations']) or NOT_STATED}"
    )
    fields["financial_details"] = f"Estimated Value: {est_val}; EMD: {emd_val}; Tender Fee: {fee_val}"
    fields["tender_status"] = evaluate_tender_status(
        deadline_d,
        pub_d,
        is_cancelled=is_cancelled,
        is_extended=is_extended,
    )

    claims: list[Claim] = [
        Claim("title", title, f"Title: {title}"),
        Claim("reference_number", ref_no, f"Tender Reference Number: {ref_no} (Tender ID: {tender_id})"),
        Claim("issuing_organisation", issuing_auth, f"Organisation Chain: {org_chain or issuing_auth}"),
    ]
    if deadline_d:
        claims.append(Claim("deadline", deadline_d.isoformat(), f"Bid Submission End Date / Closing Date: {sub_end_raw}"))
    if bid_open_d:
        claims.append(Claim("bid_opening_date", bid_open_d.isoformat(), f"Bid Opening Date: {open_raw}"))
    if est_val != NOT_PUBLISHED:
        claims.append(Claim("estimated_value", est_val, f"Tender Value in ₹: {raw_val}"))
    if emd_val != NOT_PUBLISHED:
        claims.append(Claim("emd_amount", emd_val, f"EMD Amount in ₹: {raw_emd}"))
    if fee_val != NOT_PUBLISHED:
        claims.append(Claim("tender_fee", fee_val, f"Tender Fee in ₹: {raw_fee}"))

    docs = detail_kv.get("_documents") or []
    return ExtractedItem(
        external_key=f"cppp:{tender_id}",
        title=title,
        original_url=listing_url,
        application_url=listing_url,
        raw_text=raw_text[:15_000],
        fields=fields,
        claims=claims,
        documents=docs if isinstance(docs, list) else [],
        related_notices=corr_history,
        subcategory=(t_cat.lower() if t_cat != NOT_STATED else "procurement"),
    )


def cppp_eprocure(source: Source, ctx: ScanContext) -> list[ExtractedItem]:
    """Discovers active central government tenders and corrigendums from eprocure.gov.in."""
    res = ctx.http.get(source.url)
    html = res.text
    ctx.capture(source.url, res.final_url, "http", res.status, visible_text(html))

    tenders, corrigendums = parse_cppp_home_tables(html, res.final_url)
    ctx.step("cppp.tables_parsed", active_tenders=len(tenders), corrigendums=len(corrigendums))

    max_details = int(source.config.get("max_detail_pages", 5))
    items: list[ExtractedItem] = []
    details_fetched = 0

    for entry in tenders:
        detail_kv: dict = {}
        if entry.get("detail_url") and details_fetched < max_details:
            try:
                d_res = ctx.http.get(entry["detail_url"])
                details_fetched += 1
                detail_kv = parse_cppp_detail_page(d_res.text)
                ctx.capture(entry["detail_url"], d_res.final_url, "http", d_res.status, detail_kv.get("_raw_text", "")[:100_000])
                ctx.step("cppp.detail_parsed", ref=entry["reference_number"], tender_id=detail_kv.get("Tender ID"))
            except (FetchError, BlockedError) as ex:
                ctx.step("cppp.detail_error", ref=entry["reference_number"], error=str(ex)[:160])

        items.append(build_cppp_item(entry, detail_kv=detail_kv, corrigendums=corrigendums, listing_url=res.final_url))

    return items


# --------------------------------------------------------------------------- 7. SIDBI Institutional Tenders Parser
SARFAESI_AUCTION_RE = re.compile(r"\b(SARFAESI|SARFESAI|E-Auction\s+Sale\s+Notice|Sale\s+notice\s+for\s+immovable)\b", re.I)
SIDBI_CHALLENGE_FUND_RE = re.compile(
    r"\b(innovation\s+challenge\s+fund|challenge\s+fund|cohort\s+applications?\s+open)\b",
    re.I,
)
SIDBI_FUNDING_ANNOUNCEMENT_RE = re.compile(
    r"\b(funding\s+applications?\s+open|grant\s+programme\s+applications?|seed\s+fund\s+applications?|"
    r"financial\s+assistance\s+scheme|equity\s+support\s+scheme|venture\s+debt\s+programme)\b",
    re.I,
)
SIDBI_EMPANELMENT_RE = re.compile(r"\b(empanelment|registration\s+of\s+vendors?)\b", re.I)
SIDBI_PROCUREMENT_RE = re.compile(
    r"\b(request\s+for\s+proposal|rfp|rfq|eoi|expression\s+of\s+interest|tender|bid|quotation|"
    r"corrigendum|addendum|procurement|supply|install\w*|commission\w*|hiring|engagement|"
    r"appointment|selection|renewal\s+of\s+subscription|amc|annual\s+maintenance|shifting)\b",
    re.I,
)


def classify_sidbi_notice(title: str) -> dict:
    """Classifies a SIDBI notice into procurement RFP, vendor empanelment, funding/innovation challenge,
    SARFAESI auction, or ambiguous notice requiring manual review.
    """
    t = clean_text(title)
    if SARFAESI_AUCTION_RE.search(t):
        return {
            "notice_type": "sarfaesi_auction",
            "routed_category": None,
            "subcategory": None,
            "tender_category": None,
            "is_tender": False,
            "manual_review_required": False,
            "skip_reason": "SARFAESI Act distressed-asset recovery auction, not a procurement tender",
        }
    if SIDBI_CHALLENGE_FUND_RE.search(t):
        return {
            "notice_type": "innovation_challenge_fund",
            "routed_category": "funding",
            "subcategory": "innovation_challenge",
            "tender_category": None,
            "is_tender": False,
            "manual_review_required": False,
            "skip_reason": None,
        }
    if SIDBI_FUNDING_ANNOUNCEMENT_RE.search(t):
        return {
            "notice_type": "funding_application_announcement",
            "routed_category": "funding",
            "subcategory": "funding_programme",
            "tender_category": None,
            "is_tender": False,
            "manual_review_required": False,
            "skip_reason": None,
        }
    if SIDBI_EMPANELMENT_RE.search(t):
        return {
            "notice_type": "vendor_empanelment",
            "routed_category": "tender",
            "subcategory": "empanelment",
            "tender_category": "Empanelment",
            "is_tender": True,
            "manual_review_required": False,
            "skip_reason": None,
        }
    if SIDBI_PROCUREMENT_RE.search(t):
        low = t.lower()
        t_cat = "Services" if ("rfp" in low or "hiring" in low or "engagement" in low) else "Goods"
        return {
            "notice_type": "procurement_rfp",
            "routed_category": "tender",
            "subcategory": t_cat.lower(),
            "tender_category": t_cat,
            "is_tender": True,
            "manual_review_required": False,
            "skip_reason": None,
        }
    return {
        "notice_type": "ambiguous_sidbi_notice",
        "routed_category": "tender",
        "subcategory": "under_review",
        "tender_category": "Under review",
        "is_tender": True,
        "manual_review_required": True,
        "skip_reason": None,
    }


def parse_sidbi_tender_rows(html: str, base_url: str = "https://www.sidbi.in/en/tenders") -> list[ExtractedItem]:
    """Parses SIDBI tender table rows, excluding SARFAESI auctions, routing funding/challenge notices
    to funding, and flagging ambiguous notices for manual review while preserving evidence.
    """
    s = soup_of(html)
    items: list[ExtractedItem] = []

    for tb in s.find_all("table"):
        for tr in tb.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < 4:
                continue
            sno = clean_text(tds[0].get_text(" ", strip=True))
            title = clean_text(tds[1].get_text(" ", strip=True))
            pub_raw = clean_text(tds[2].get_text(" ", strip=True))
            close_raw = clean_text(tds[3].get_text(" ", strip=True))
            remark = clean_text(tds[4].get_text(" ", strip=True)) if len(tds) > 4 else ""

            if not title or title.lower() == "title":
                continue

            a = tds[1].find("a", href=True)
            href = a["href"] if a else ""
            if href and not href.startswith(("http://", "https://", "/")):
                detail_url = f"https://www.sidbi.in/en/{href.lstrip('/')}"
            else:
                detail_url = safe_link(href, base_url) or base_url

            slug_key = href.rstrip("/").split("/")[-1][:80] if href else f"row-{sno}-{title[:40]}"
            notice_cls = classify_sidbi_notice(title)

            # Filter out SARFAESI property recovery auctions
            if notice_cls["skip_reason"]:
                items.append(
                    ExtractedItem(
                        external_key=f"skip:sidbi:{slug_key}",
                        title=title,
                        original_url=detail_url,
                        raw_text=f"{title} | {pub_raw} | {close_raw} | {remark}",
                        skip_reason=notice_cls["skip_reason"],
                    )
                )
                continue

            pub_d = parse_date(pub_raw)
            close_d = parse_date(close_raw) or parse_date(remark)

            if notice_cls["routed_category"] == "funding":
                ref_no = f"SIDBI/FUND/{pub_d.isoformat() if pub_d else '2026'}/{sno}"
                raw_text = f"SIDBI Funding & Innovation Notice | Title: {title} | Date: {pub_raw} | Last Date: {close_raw} | {remark}"
                sector = classify_sector(
                    title,
                    product_category=title,
                    tender_category="Services",
                    title=title,
                    buyer_text="Small Industries Development Bank of India",
                )
                state, city, loc_type = classify_geography(title, org_chain="Small Industries Development Bank of India")
                fields: dict = {
                    "routed_category": "funding",
                    "sidbi_notice_type": notice_cls["notice_type"],
                    "reference_number": ref_no,
                    "issuing_organisation": "Small Industries Development Bank of India (SIDBI)",
                    "department": "SIDBI Innovation & Venture Funding Cell",
                    "industry": sector,
                    "sector": sector,
                    "state": state,
                    "city": city,
                    "location_type": loc_type,
                    "eligibility": "Refer to official SIDBI Innovation Challenge / Funding announcement guidelines",
                    "financial_details": "Grant / Challenge Fund support as per official SIDBI programme guidelines",
                    "application_method": "Online application via official SIDBI portal (www.sidbi.in)",
                }
                if pub_d:
                    fields["published_date"] = pub_d.isoformat()
                    fields["opening_date"] = pub_d.isoformat()
                if close_d:
                    fields["deadline"] = close_d.isoformat()

                claims = [
                    Claim("title", title, f"Title: {title}"),
                    Claim("issuing_organisation", "Small Industries Development Bank of India (SIDBI)", "SIDBI Official Portal"),
                    Claim("reference_number", ref_no, f"S. No. {sno} | Date: {pub_raw}"),
                ]
                if pub_d:
                    claims.append(Claim("published_date", pub_d.isoformat(), f"Tender Date: {pub_raw}"))
                if close_d:
                    claims.append(Claim("deadline", close_d.isoformat(), f"Last Date Of Submission: {close_raw} ({remark})"))

                items.append(
                    ExtractedItem(
                        external_key=f"sidbi-tender:{slug_key[:80]}",
                        title=title,
                        original_url=base_url,
                        application_url=base_url,
                        raw_text=raw_text,
                        fields=fields,
                        claims=claims,
                        subcategory=notice_cls["subcategory"] or "innovation_challenge",
                    )
                )
                continue

            ref_no = f"SIDBI/TENDER/{pub_d.isoformat() if pub_d else '2026'}/{sno}"
            raw_text = f"SIDBI Institutional Tender | Title: {title} | Tender Date: {pub_raw} | Last Date: {close_raw} | {remark}"
            t_cat = notice_cls["tender_category"] or "Goods"
            sector = classify_sector(
                title,
                product_category=title,
                tender_category=t_cat,
                title=title,
                buyer_text="Small Industries Development Bank of India",
            )
            state, city, loc_type = classify_geography(title, org_chain="Small Industries Development Bank of India")
            elig_intel = extract_eligibility_intelligence(raw_text)
            if notice_cls["manual_review_required"]:
                elig_intel["ambiguous_flag"] = True

            t_status = (
                TenderStatus.UNDER_VERIFICATION.value
                if notice_cls["manual_review_required"]
                else evaluate_tender_status(close_d, pub_d)
            )

            fields = {
                "routed_category": "tender",
                "sidbi_notice_type": notice_cls["notice_type"],
                "manual_review_required": notice_cls["manual_review_required"],
                "tender_id": f"sidbi:{slug_key[:64]}",
                "reference_number": ref_no,
                "issuing_organisation": "Small Industries Development Bank of India (SIDBI)",
                "department": "SIDBI Institutional Procurement & Vendor Cell",
                "tender_category": t_cat,
                "product_category": title[:200],
                "industry": sector,
                "sector": sector,
                "state": state,
                "city": city,
                "location_type": loc_type,
                "estimated_value": NOT_PUBLISHED,
                "emd_amount": NOT_PUBLISHED,
                "tender_fee": NOT_PUBLISHED,
                "pre_bid_details": NOT_PUBLISHED,
                "turnover_requirement": elig_intel["turnover_conditions"],
                "experience_requirement": elig_intel["experience_conditions"],
                "experience": elig_intel["experience_conditions"],
                "msme_preference": elig_intel["msme_eligibility"],
                "eligibility_intelligence": elig_intel,
                "required_registrations": elig_intel["required_registrations"],
                "eligibility": "Refer to official SIDBI RFP / Empanelment tender notice",
                "financial_details": f"Estimated Value: {NOT_PUBLISHED}; EMD: {NOT_PUBLISHED}",
                "application_method": "Submission as specified in SIDBI official tender notice (www.sidbi.in/en/tenders)",
                "tender_status": t_status,
            }
            if pub_d:
                fields["published_date"] = pub_d.isoformat()
                fields["opening_date"] = pub_d.isoformat()
            if close_d:
                fields["deadline"] = close_d.isoformat()

            claims = [
                Claim("title", title, f"Title: {title}"),
                Claim("issuing_organisation", "Small Industries Development Bank of India (SIDBI)", "SIDBI Official Tenders Portal"),
                Claim("reference_number", ref_no, f"S. No. {sno} | Tender Date: {pub_raw}"),
            ]
            if pub_d:
                claims.append(Claim("published_date", pub_d.isoformat(), f"Tender Date: {pub_raw}"))
            if close_d:
                claims.append(Claim("deadline", close_d.isoformat(), f"Last Date Of Submission: {close_raw} ({remark})"))

            items.append(
                ExtractedItem(
                    external_key=f"sidbi-tender:{slug_key[:80]}",
                    title=title,
                    original_url=base_url,
                    application_url=base_url,
                    raw_text=raw_text,
                    fields=fields,
                    claims=claims,
                    subcategory=notice_cls["subcategory"] or t_cat.lower(),
                )
            )
    return items


def sidbi_tenders(source: Source, ctx: ScanContext) -> list[ExtractedItem]:
    """Renders SIDBI's official tenders page via headless Chromium and extracts genuine procurement RFPs."""
    page = ctx.browser.render(source.url, wait_for_selector="table tr td")
    ctx.capture(source.url, page.final_url, "browser", page.status, visible_text(page.html))
    items = parse_sidbi_tender_rows(page.html, page.final_url)
    ctx.step(
        "sidbi_tenders.parsed",
        total_rows=len(items),
        active_rfps=sum(1 for i in items if not i.skip_reason and i.fields.get("routed_category") != "funding"),
        routed_funding=sum(1 for i in items if not i.skip_reason and i.fields.get("routed_category") == "funding"),
        skipped_sarfaesi=sum(1 for i in items if i.skip_reason),
    )
    return items


class TenderScout(BaseAgent):
    agent_id = "tender_scout"
    name = "Tender Scout"
    description = "Discovers, extracts, classifies, and monitors official government & PSU procurement tenders."
    config = AgentConfig(
        category="tender",
        mandatory_fields=["title", "original_url", "reference_number"],
        subcategories=["goods", "services", "works", "consultancy", "empanelment", "procurement", "under_review"],
    )
    parsers = {
        "gem_public_bids": gem_public_bids,
        "cppp_eprocure": cppp_eprocure,
        "sidbi_tenders": sidbi_tenders,
    }

    def validate(self, item: ExtractedItem) -> list[str]:
        issues = super().validate(item)
        if item.fields.get("routed_category") == "funding":
            return issues
        if not item.fields.get("sector"):
            issues.append("missing BECCI sector classification")
        if not item.fields.get("tender_status"):
            issues.append("missing tender_status")
        return issues
