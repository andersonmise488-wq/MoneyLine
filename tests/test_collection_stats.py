from __future__ import annotations

from moneyline.pipeline.collection_stats import CollectionStats


def test_weak_bookmakers_detects_low_soccer_coverage() -> None:
    stats = CollectionStats()
    stats.set_row(
        bookmaker="odibets",
        sport="soccer",
        events=2,
        events_with_markets=2,
        markets=10,
    )
    stats.set_row(
        bookmaker="sportpesa",
        sport="soccer",
        events=200,
        events_with_markets=180,
        markets=900,
    )
    stats.set_row(
        bookmaker="bangbet",
        sport="volleyball",
        events=0,
        events_with_markets=0,
        markets=0,
    )
    stats.set_row(
        bookmaker="betpawa",
        sport="cricket",
        events=0,
        events_with_markets=0,
        markets=0,
        skipped=True,
        error="no sport mapping",
    )
    weak = stats.weak_bookmakers(min_events=10)
    assert "odibets" in weak
    assert "sportpesa" not in weak
    assert "betpawa" not in weak
    assert "bangbet" not in weak


def test_weak_bookmakers_ignores_niche_gaps_when_soccer_healthy() -> None:
    stats = CollectionStats()
    stats.set_row(
        bookmaker="sportybet",
        sport="soccer",
        events=120,
        events_with_markets=100,
        markets=500,
    )
    stats.set_row(
        bookmaker="sportybet",
        sport="volleyball",
        events=0,
        events_with_markets=0,
        markets=0,
    )
    stats.set_row(
        bookmaker="pepeta",
        sport="soccer",
        events=132,
        events_with_markets=100,
        markets=400,
    )
    stats.set_row(
        bookmaker="pepeta",
        sport="tennis",
        events=0,
        events_with_markets=0,
        markets=0,
    )
    weak = stats.weak_bookmakers()
    assert "sportybet" not in weak
    assert "pepeta" not in weak


def test_collection_stats_to_dict() -> None:
    stats = CollectionStats()
    stats.set_row(
        bookmaker="betika",
        sport="soccer",
        events=100,
        events_with_markets=95,
        markets=400,
    )
    payload = stats.to_dict()
    assert payload["betika:soccer"]["events"] == 100
    assert payload["betika:soccer"]["events_with_markets"] == 95
