"""Tests for Central Source Registry."""
from app.db import session_scope
from app.models import CentralSourceRegistry
from app.pipeline.central_source_registry import seed_central_source_registry


def test_seed_and_query_central_source_registry():
    with session_scope() as session:
        count = seed_central_source_registry(session)
        assert count >= 0

        sources = session.query(CentralSourceRegistry).all()
        assert len(sources) >= 14

        gem = session.query(CentralSourceRegistry).filter_by(id="gem-procurement-portal").first()
        assert gem is not None
        assert gem.domain == "gem.gov.in"
        assert "gem_procurement" in gem.supported_categories
        assert gem.health_status == "healthy"

        tg = session.query(CentralSourceRegistry).filter_by(id="tg-tpride-industries").first()
        assert tg is not None
        assert "Telangana" in tg.geographic_coverage
