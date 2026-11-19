import datetime as dt
from app.pipeline.extraction import (
    DEADLINE_PATTERNS,
    OPENING_PATTERNS,
    clean_text,
    find_dated_claim,
    find_reference,
    find_vacancies,
    parse_date,
    title_key,
)


def test_clean_text():
    raw = "   DIRECT RECRUITMENT   FOR  THE POST \u200bOF MANAGER\n\n\t "
    assert clean_text(raw) == "DIRECT RECRUITMENT FOR THE POST OF MANAGER"


def test_parse_date():
    assert parse_date("17/10/2026") == dt.date(2026, 10, 17)
    assert parse_date("23-09-2026") == dt.date(2026, 9, 23)
    assert parse_date("18th November 2026") == dt.date(2026, 11, 18)
    assert parse_date("November 23, 2026") == dt.date(2026, 11, 23)


def test_find_dated_claims():
    text = (
        "Submission of Online Application From: 23/09/2026. "
        "Last Date & Time of submission of Online Application 17/10/2026 at 5:00 PM."
    )
    c_open = find_dated_claim(text, OPENING_PATTERNS, "opening_date")
    assert c_open is not None
    assert c_open.value == "2026-09-23"

    c_dead = find_dated_claim(text, DEADLINE_PATTERNS, "deadline")
    assert c_dead is not None
    assert c_dead.value == "2026-10-17"


def test_find_reference():
    text = "NOTIFICATION NO. 04/OG/HM/2026, Dt. 18/09/2026"
    c_ref = find_reference(text)
    assert c_ref is not None
    assert "04/OG/HM/2026" in c_ref.value


def test_find_vacancies():
    text = "Total No. of Vacancies: 154 posts across state cadre."
    c_vac = find_vacancies(text)
    assert c_vac is not None
    assert c_vac.value == "154"


def test_title_key():
    assert title_key("Advt. No. 017/2026: Group-C Preliminary Exam!!") == "advt no 017 2026 group c preliminary exam"
