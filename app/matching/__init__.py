"""Phase 3 Opportunity Matching, Eligibility Intelligence & Configurable Ranking Engine."""
from app.matching.engine import (
    ELIGIBILITY_DISCLAIMER,
    evaluate_match,
    get_or_create_matching_config,
    is_incomplete_eligibility,
    rank_opportunities_for_profile,
)

__all__ = [
    "ELIGIBILITY_DISCLAIMER",
    "evaluate_match",
    "get_or_create_matching_config",
    "is_incomplete_eligibility",
    "rank_opportunities_for_profile",
]
