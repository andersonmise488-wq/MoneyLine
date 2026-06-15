"""Tests for raw odds file cache."""

from __future__ import annotations

from datetime import datetime, timezone

from moneyline.models.schemas import Bookmaker, MarketOdds, OddsOutcome, OutcomeSide, Sport
from moneyline.storage.raw_cache import RawOddsCache


def _sample_markets() -> list[MarketOdds]:
    return [
        MarketOdds(
            event_key="betika:42",
            bookmaker=Bookmaker.BETIKA,
            sport=Sport.TENNIS,
            market_key="match_winner",
            market_display="Match Winner",
            outcomes=[OddsOutcome(side=OutcomeSide.HOME, label="P1", price=1.85)],
        )
    ]


def test_cache_miss_returns_none(tmp_path):
    cache = RawOddsCache(root=tmp_path)
    assert cache.get("betika", "tennis", "missing") is None


def test_cache_hit_after_put(tmp_path):
    cache = RawOddsCache(root=tmp_path, ttl_seconds=300)
    cache.put("betika", "tennis", "42", _sample_markets())
    hit = cache.get("betika", "tennis", "42")
    assert hit is not None
    assert hit[0].sport == Sport.TENNIS
