import datetime as dt
from app.db import Base, get_engine, session_scope
from app.enums import LifecycleStatus, SourceReliability, VerificationStatus
from app.models import Opportunity, Source, utcnow
from app.pipeline.verification import verify_opportunity


def setup_module():
    engine = get_engine()
    Base.metadata.create_all(bind=engine)


def test_verify_opportunity_domain_and_evidence():
    with session_scope() as session:
        src = Source(
            id="test-source",
            name="Test Source",
            domain="example.gov.in",
            url="https://example.gov.in",
            agent_id="job_scout",
            parser="test",
            categories=["job"],
            geographic_coverage=["National"],
            industry_relevance=["Public"],
            collection_method="http_html",
            reliability=SourceReliability.OFFICIAL_GOVERNMENT,
            issuing_organisation="Example Commission",
            official_domains=["example.gov.in"],
        )
        session.merge(src)

        opp = Opportunity(
            id="opp-test-1",
            external_key="key-1",
            slug="test-job-opp-1",
            title="Assistant Engineer Examination 2026",
            category="job",
            issuing_organisation="Example Commission",
            publisher="Example Commission",
            source_type=SourceReliability.OFFICIAL_GOVERNMENT,
            source_name="Test Source",
            original_url="https://example.gov.in/notices/123",
            source_id="test-source",
            agent_id="job_scout",
            content_fingerprint="abc",
            title_fingerprint="def",
            raw_title="raw title",
            raw_text="raw body text",
            extracted_at=utcnow(),
        )
        session.merge(opp)

        # Verification without evidence -> INSUFFICIENT_EVIDENCE
        v_rec = verify_opportunity(session, opp, src)
        assert v_rec.status == VerificationStatus.INSUFFICIENT_EVIDENCE
        assert opp.lifecycle_status == LifecycleStatus.NEEDS_HUMAN_REVIEW


def test_verify_expired_opportunity():
    with session_scope() as session:
        src = session.get(Source, "test-source")
        opp = Opportunity(
            id="opp-test-expired",
            external_key="key-exp",
            slug="test-job-expired",
            title="Past Exam 2020",
            category="job",
            issuing_organisation="Example Commission",
            publisher="Example Commission",
            source_type=SourceReliability.OFFICIAL_GOVERNMENT,
            source_name="Test Source",
            original_url="https://example.gov.in/notices/expired",
            deadline=dt.date(2020, 1, 1),  # Past date
            source_id="test-source",
            agent_id="job_scout",
            content_fingerprint="abc",
            title_fingerprint="def",
            raw_title="raw title",
            raw_text="raw body text",
            extracted_at=utcnow(),
        )
        session.merge(opp)

        v_rec = verify_opportunity(session, opp, src)
        assert v_rec.status == VerificationStatus.EXPIRED
        assert opp.lifecycle_status == LifecycleStatus.EXPIRED
