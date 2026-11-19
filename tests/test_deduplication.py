import datetime as dt
from app.db import session_scope
from app.enums import LifecycleStatus, SourceReliability
from app.models import Opportunity, utcnow
from app.pipeline.deduplication import handle_deduplication_and_changes


def test_deduplication_exact_key_change_detection():
    with session_scope() as session:
        # Create initial opportunity
        opp1 = Opportunity(
            id="dedup-opp-1",
            external_key="ext-test-1",
            slug="test-opp-1",
            title="Initial Title Post",
            category="job",
            issuing_organisation="Test Org",
            publisher="Test Publisher",
            source_type=SourceReliability.OFFICIAL_GOVERNMENT,
            source_name="Test Source",
            original_url="https://test.gov.in/post/1",
            source_id="tgpsc-whats-new",
            agent_id="job_scout",
            content_fingerprint="hash1",
            title_fingerprint="thash1",
            raw_title="Initial Title Post",
            raw_text="Initial text body",
            deadline=dt.date(2026, 12, 1),
            lifecycle_status=LifecycleStatus.PUBLISHED,
            extracted_at=utcnow(),
        )
        session.add(opp1)
        session.flush()

        # Second scan finds updated deadline and raw text
        opp2 = Opportunity(
            id="dedup-opp-2",
            external_key="ext-test-1",  # Same external key
            slug="test-opp-2",
            title="Initial Title Post",
            category="job",
            issuing_organisation="Test Org",
            publisher="Test Publisher",
            source_type=SourceReliability.OFFICIAL_GOVERNMENT,
            source_name="Test Source",
            original_url="https://test.gov.in/post/1",
            source_id="tgpsc-whats-new",
            agent_id="job_scout",
            content_fingerprint="hash2",
            title_fingerprint="thash1",
            raw_title="Initial Title Post",
            raw_text="Updated text body with extended deadline",
            deadline=dt.date(2026, 12, 15),  # Extended deadline!
            extracted_at=utcnow(),
        )

        action, updated_opp = handle_deduplication_and_changes(session, opp2)
        session.flush()
        assert action == "updated"
        assert updated_opp.id == "dedup-opp-1"
        assert updated_opp.deadline == dt.date(2026, 12, 15)
        assert updated_opp.lifecycle_status == LifecycleStatus.UPDATED
        assert len(updated_opp.versions) == 1
        assert "deadline" in updated_opp.versions[0].changed_fields


def test_deduplication_fuzzy_title_match():
    with session_scope() as session:
        # Opp from Source A
        opp_a = Opportunity(
            id="fuzzy-opp-a",
            external_key="sourceA-100",
            slug="fuzzy-opp-a",
            title="Assistant Engineer Electrical Recruitment 2026",
            category="job",
            issuing_organisation="Electricity Board",
            publisher="Govt Portal A",
            source_type=SourceReliability.OFFICIAL_GOVERNMENT,
            source_name="Source A",
            original_url="https://a.gov.in/job1",
            source_id="tgpsc-whats-new",
            agent_id="job_scout",
            content_fingerprint="hashA",
            title_fingerprint="tA",
            raw_title="raw title A",
            raw_text="raw text A",
            lifecycle_status=LifecycleStatus.PUBLISHED,
            extracted_at=utcnow(),
        )
        session.add(opp_a)
        session.flush()

        # Near-identical Opp from Source B (Third-party aggregator or secondary portal)
        opp_b = Opportunity(
            id="fuzzy-opp-b",
            external_key="sourceB-999",
            slug="fuzzy-opp-b",
            title="Recruitment for Assistant Engineer Electrical 2026",
            category="job",
            issuing_organisation="Electricity Board",
            publisher="Aggregator B",
            source_type=SourceReliability.THIRD_PARTY,
            source_name="Source B",
            original_url="https://b.com/job1",
            source_id="sidbi-schemes",  # Secondary source
            agent_id="job_scout",
            content_fingerprint="hashB",
            title_fingerprint="tB",
            raw_title="raw title B",
            raw_text="raw text B",
            extracted_at=utcnow(),
        )

        action, merged_opp = handle_deduplication_and_changes(session, opp_b)
        assert action == "merged_duplicate"
        assert merged_opp.id == "fuzzy-opp-a"
        assert len(merged_opp.supporting_sources) == 1
        assert merged_opp.supporting_sources[0].url == "https://b.com/job1"
