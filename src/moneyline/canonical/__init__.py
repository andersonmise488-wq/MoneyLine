"""Canonical entity and market models for production-grade cross-book matching."""

from moneyline.canonical.entities import (
    BookEventLink,
    Fixture,
    canonical_team_id,
    fixture_id_for,
    normalize_team_canonical,
)
from moneyline.canonical.markets import MarketSpec, market_spec_id
from moneyline.matching.confidence import MatchConfidence

__all__ = [
    "BookEventLink",
    "Fixture",
    "MarketSpec",
    "MatchConfidence",
    "canonical_team_id",
    "fixture_id_for",
    "market_spec_id",
    "normalize_team_canonical",
]
