"""Tests for Real-Time Status and Deadline Intelligence."""
import datetime as dt
from app.enums import ExpiryStatus, RealtimeStatus
from app.pipeline.deadline_intelligence import evaluate_deadline_intelligence


def test_deadline_intelligence_closing_soon():
    today = dt.date(2026, 11, 23)
    deadline = dt.date(2026, 11, 27)  # 4 days away
    status, days_rem, expiry = evaluate_deadline_intelligence(
        deadline=deadline,
        reference_now=today
    )
    assert status == RealtimeStatus.CLOSING_SOON
    assert days_rem == 4
    assert expiry == ExpiryStatus.CLOSING_SOON


def test_deadline_intelligence_closed():
    today = dt.date(2026, 11, 23)
    deadline = dt.date(2026, 11, 20)  # 3 days in the past
    status, days_rem, expiry = evaluate_deadline_intelligence(
        deadline=deadline,
        reference_now=today
    )
    assert status == RealtimeStatus.CLOSED
    assert days_rem == -3
    assert expiry == ExpiryStatus.EXPIRED


def test_deadline_intelligence_open():
    today = dt.date(2026, 11, 23)
    deadline = dt.date(2026, 12, 31)  # 38 days away
    status, days_rem, expiry = evaluate_deadline_intelligence(
        deadline=deadline,
        reference_now=today
    )
    assert status == RealtimeStatus.OPEN
    assert days_rem == 38
    assert expiry == ExpiryStatus.ACTIVE


def test_deadline_intelligence_date_unavailable():
    today = dt.date(2026, 11, 23)
    status, days_rem, expiry = evaluate_deadline_intelligence(
        deadline=None,
        reference_now=today
    )
    assert status == RealtimeStatus.OPEN
    assert days_rem is None
    assert expiry == ExpiryStatus.DATE_UNAVAILABLE
