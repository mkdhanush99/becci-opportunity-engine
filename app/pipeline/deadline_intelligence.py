"""Real-Time Status and Deadline Intelligence.

Complies with Master Autonomous Build Directive Section 9:
- Determines status deterministically from original source information and actual current runtime date.
- Calculates exact days remaining.
- Detects amended dates and corrigenda.
- Never guesses or invents deadlines.
- Enforces: Expired opportunities must NEVER appear as open.
"""
from __future__ import annotations

import datetime as dt
from typing import Optional, Tuple

from app.enums import ExpiryStatus, RealtimeStatus


def evaluate_deadline_intelligence(
    deadline: Optional[dt.date],
    opening_date: Optional[dt.date] = None,
    amendment_detected_at: Optional[dt.datetime] = None,
    is_cancelled: bool = False,
    is_suspended: bool = False,
    needs_verification: bool = False,
    reference_now: Optional[dt.date] = None,
) -> Tuple[str, Optional[int], str]:
    """Evaluates real-time status, days remaining, and expiry status.
    
    Returns:
        (realtime_status, days_remaining, expiry_status)
    """
    now_date = reference_now or dt.datetime.now(dt.timezone.utc).date()

    if is_cancelled:
        return RealtimeStatus.CANCELLED, None, ExpiryStatus.EXPIRED

    if is_suspended:
        return RealtimeStatus.SUSPENDED, None, ExpiryStatus.ACTIVE

    if needs_verification:
        return RealtimeStatus.VERIFICATION_REQUIRED, None, ExpiryStatus.DATE_UNAVAILABLE

    if not deadline:
        # Date unavailable - cannot be marked closing soon or expired without date
        return RealtimeStatus.OPEN, None, ExpiryStatus.DATE_UNAVAILABLE

    # Calculate days remaining
    days_remaining = (deadline - now_date).days

    if days_remaining < 0:
        # Strictly expired
        return RealtimeStatus.CLOSED, days_remaining, ExpiryStatus.EXPIRED

    if amendment_detected_at is not None:
        return RealtimeStatus.AMENDED, days_remaining, (
            ExpiryStatus.CLOSING_SOON if days_remaining <= 7 else ExpiryStatus.ACTIVE
        )

    if days_remaining <= 7:
        return RealtimeStatus.CLOSING_SOON, days_remaining, ExpiryStatus.CLOSING_SOON

    return RealtimeStatus.OPEN, days_remaining, ExpiryStatus.ACTIVE


def refresh_opportunity_deadline_intelligence(opp, reference_now: Optional[dt.date] = None) -> None:
    """Updates an Opportunity instance with computed real-time deadline intelligence."""
    is_cancelled = False
    if hasattr(opp, "tender_detail") and opp.tender_detail and opp.tender_detail.cancellation_reason:
        is_cancelled = True

    status, days_rem, expiry = evaluate_deadline_intelligence(
        deadline=opp.deadline,
        opening_date=opp.opening_date,
        amendment_detected_at=getattr(opp, "amendment_detected_at", None),
        is_cancelled=is_cancelled,
        needs_verification=getattr(opp, "needs_reverification", False),
        reference_now=reference_now,
    )

    opp.realtime_status = status
    opp.days_remaining = days_rem
    opp.expiry_status = expiry
