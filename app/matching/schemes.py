"""Eligibility assessment engine for Central, Telangana, and Andhra Pradesh Government Schemes.

Evaluates user/member profile parameters against official SchemeDetail criteria:
- State domicile
- Central OBC list vs State BC lists (BC-A, BC-B, BC-C, BC-D, BC-E)
- Non-creamy-layer requirement
- Annual family income
- Age limits
- Education and occupation conditions
- Gender or specific beneficiary restrictions

Strict Safety Principle:
Never promises a grant, subsidy, loan or scholarship. Assessments are informational and advisory.
"""
from __future__ import annotations

import re
from typing import Any
from app.enums import SchemeEligibilityAssessmentStatus
from app.models import SchemeDetail
from app.schemas import SchemeEligibilityAssessmentOut

SCHEME_ELIGIBILITY_DISCLAIMER = (
    "Eligibility assessment is advisory only based on user-supplied parameters. "
    "BECCI does not promise or guarantee approval of any grant, subsidy, loan or scholarship. "
    "Final eligibility is determined exclusively by the respective issuing government department."
)

_INCOME_PARSE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:lakh|lakhs|l|lac|lacs)?", re.I)


def parse_numeric_income(val: Any) -> float | None:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).replace(",", "").strip().lower()
    if not s or s in ("not stated", "na", "null", "none"):
        return None
    m = re.search(r"(\d+(?:\.\d+)?)", s)
    if not m:
        return None
    num = float(m.group(1))
    if "lakh" in s or "lac" in s or "l" in s:
        return num * 100_000
    if "crore" in s or "cr" in s:
        return num * 10_000_000
    return num


def evaluate_scheme_eligibility(
    scheme: SchemeDetail,
    applicant_data: dict[str, Any],
) -> SchemeEligibilityAssessmentOut:
    """Evaluates an applicant against a SchemeDetail record.
    
    applicant_data can contain:
    - domicile_state: str (e.g. 'Telangana', 'Andhra Pradesh')
    - caste_community: str (e.g. 'OBC', 'BC-B', 'General')
    - is_non_creamy_layer: bool | None
    - annual_family_income: float | str | None
    - age: int | None
    - education: str | None
    - occupation: str | None
    - is_entrepreneur: bool | None
    - gender: str | None ('female', 'male', 'other')
    """
    matched: list[str] = []
    unmatched: list[str] = []
    missing: list[str] = []

    # 1. Domicile Verification
    domicile = applicant_data.get("domicile_state")
    if scheme.domicile_required:
        req_state = scheme.domicile_state
        if not domicile:
            missing.append(f"State domicile confirmation required (Scheme requires {req_state} residency)")
        elif domicile.strip().lower() == (req_state or "").strip().lower():
            matched.append(f"Applicant is a verified resident of {req_state}")
        else:
            unmatched.append(
                f"Domicile mismatch: Scheme requires {req_state} domicile, but applicant is from {domicile}"
            )
    else:
        if domicile:
            matched.append(f"Pan-India scheme accessible to {domicile} applicants")

    # 2. Caste / Community Classification
    caste = applicant_data.get("caste_community")
    applicable_castes = [c.upper() for c in (scheme.applicable_castes or [])]
    is_obc_restricted = scheme.beneficiary_classification == "obc_bc_specific" or any(
        c in applicable_castes for c in ["OBC", "BC-A", "BC-B", "BC-C", "BC-D", "BC-E", "EBC", "DNT"]
    )

    if is_obc_restricted and "ALL" not in applicable_castes:
        if not caste:
            missing.append("OBC/BC community classification required to confirm eligibility")
        else:
            caste_upper = caste.strip().upper()
            is_valid_bc = any(
                c in caste_upper or caste_upper in c
                for c in ["OBC", "BC", "BC-A", "BC-B", "BC-C", "BC-D", "BC-E", "EBC", "DNT"]
            )
            if is_valid_bc:
                matched.append(f"Community criteria met: {caste} matches target backward class group")
            else:
                unmatched.append(f"Caste criteria not met: Scheme is restricted to OBC/BC communities, applicant is {caste}")
    else:
        if caste:
            matched.append("Open to all categories including BC/OBC applicants")

    # 3. Non-Creamy Layer Requirement
    is_ncl = applicant_data.get("is_non_creamy_layer")
    if is_obc_restricted and is_ncl is False:
        unmatched.append("Scheme requires Non-Creamy Layer (NCL) status; applicant is creamy layer")
    elif is_obc_restricted and is_ncl is True:
        matched.append("Non-Creamy Layer (NCL) status confirmed")

    # 4. Income Limit
    income = parse_numeric_income(applicant_data.get("annual_family_income"))
    scheme_income_max = parse_numeric_income(scheme.income_limit)
    if scheme_income_max is not None:
        if income is None:
            missing.append(f"Annual family income required (Official ceiling: {scheme.income_limit})")
        elif income <= scheme_income_max:
            matched.append(f"Income eligibility satisfied: ₹{int(income):,} is within ceiling of {scheme.income_limit}")
        else:
            unmatched.append(f"Income exceeded: ₹{int(income):,} exceeds official ceiling of {scheme.income_limit}")

    # 5. Age Limits
    age = applicant_data.get("age")
    if scheme.age_limit and scheme.age_limit.lower() not in ("not stated", "none"):
        nums = [int(n) for n in re.findall(r"\d+", scheme.age_limit)]
        if len(nums) >= 2:
            min_age, max_age = nums[0], nums[1]
            if age is None:
                missing.append(f"Age verification required (Scheme requirement: {min_age}-{max_age} years)")
            elif min_age <= age <= max_age:
                matched.append(f"Age criterion satisfied: {age} years is within {min_age}-{max_age} range")
            else:
                unmatched.append(f"Age limit not met: {age} years is outside official limit of {min_age}-{max_age} years")
        elif len(nums) == 1:
            max_age = nums[0]
            if age is None:
                missing.append(f"Age verification required (Scheme ceiling: {max_age} years)")
            elif age <= max_age:
                matched.append(f"Age criterion satisfied: {age} years is under {max_age} years")
            else:
                unmatched.append(f"Age limit exceeded: {age} years exceeds maximum of {max_age} years")

    # 6. Gender Restrictions
    gender = applicant_data.get("gender")
    is_women_only = (
        scheme.beneficiary_classification == "women_entrepreneurs"
        or "women" in (scheme.beneficiary_categories or []) and len(scheme.beneficiary_categories) == 1
        or "women" in scheme.scheme_name.lower() and "only" in scheme.scheme_name.lower()
    )
    if is_women_only:
        if not gender:
            missing.append("Gender confirmation required (Scheme exclusively for women entrepreneurs/students)")
        elif gender.strip().lower() in ("female", "woman", "women"):
            matched.append("Gender criterion satisfied: Exclusive women's welfare initiative")
        else:
            unmatched.append("Scheme is exclusively intended for women applicants")

    # Final Status Determination
    if unmatched:
        status = SchemeEligibilityAssessmentStatus.NOT_ELIGIBLE
        status_label = "Not eligible based on known conditions"
        notes = f"Application conditions are not met: {'; '.join(unmatched)}."
    elif missing and matched:
        status = SchemeEligibilityAssessmentStatus.POTENTIALLY_ELIGIBLE
        status_label = "Potentially eligible — additional information required"
        notes = f"Candidate matches preliminary criteria, but requires verification of: {'; '.join(missing)}."
    elif missing and not matched:
        status = SchemeEligibilityAssessmentStatus.CANNOT_ESTABLISH
        status_label = "Eligibility cannot be established"
        notes = "Insufficient applicant details provided to assess scheme eligibility."
    else:
        status = SchemeEligibilityAssessmentStatus.ELIGIBLE
        status_label = "Eligible based on supplied information"
        notes = "All stated eligibility criteria match the applicant's supplied profile."

    return SchemeEligibilityAssessmentOut(
        status=status.value,
        status_label=status_label,
        matched_conditions=matched,
        unmatched_conditions=unmatched,
        missing_information=missing,
        notes=notes,
        disclaimer=SCHEME_ELIGIBILITY_DISCLAIMER,
    )
