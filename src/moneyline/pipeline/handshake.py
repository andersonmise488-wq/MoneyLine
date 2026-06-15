"""Production pipeline handshake — ops diagnostics and architecture flags."""

from __future__ import annotations

from typing import Any

from moneyline.config.settings import get_settings
from moneyline.constants import MIN_MATCH_CONFIDENCE_FOR_ARB, EVENT_LOOKAHEAD_HOURS
from moneyline.events.health import evaluate_scraper_health
from moneyline.matching.review import MatchReviewQueue
from moneyline.models.schemas import Bookmaker
from moneyline.pipeline.book_health import BookHealthTracker


def architecture_flags() -> dict[str, Any]:
    """Which production architecture layers are active in the live path."""
    settings = get_settings()
    return {
        "canonical_markets": True,
        "market_spec_grouping": True,
        "market_equivalence_rules": True,
        "union_find_matching": True,
        "fixture_id": True,
        "match_confidence_gate": True,
        "min_match_confidence": MIN_MATCH_CONFIDENCE_FOR_ARB,
        "match_review_queue": True,
        "odds_staleness_seconds": settings.odds_staleness_seconds,
        "alert_routing_bands": True,
        "book_circuit_breaker": True,
        "match_first_markets": settings.match_first_markets,
        "raw_odds_cache": settings.raw_cache_ttl_seconds > 0,
        "opportunity_dedup": True,
        "deep_links": True,
    }


def build_ops_diagnostics(
    *,
    book_health: BookHealthTracker | None = None,
    events_collected: int | None = None,
    lookahead_hours: int | None = None,
) -> dict[str, Any]:
    """Aggregate cross-layer ops state after a scan cycle."""
    tracker = book_health or BookHealthTracker()
    tracker.prune_expired_cooldowns()
    review_items = MatchReviewQueue().list_items(limit=100)
    books = tracker.snapshot()
    paused: list[str] = []
    for name in books:
        try:
            if not tracker.is_available(Bookmaker(name)):
                paused.append(name)
        except ValueError:
            continue
    paused = sorted(paused)
    ops: dict[str, Any] = {
        "book_health": books,
        "books_paused": sorted(paused),
        "match_review_count": len(review_items),
        "architecture": architecture_flags(),
    }
    if events_collected is not None:
        ops["scraper"] = evaluate_scraper_health(
            events_collected,
            lookahead_hours=lookahead_hours or EVENT_LOOKAHEAD_HOURS,
        )
    return ops
