from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from moneyline.alerts.routing import filter_public_feed, filter_telegram_alerts
from moneyline.canonical.markets import is_blocked_market_family, reject_integer_totals_enabled, raw_name_blocked
from moneyline.matching.competitions import canonical_competition_name
from moneyline.matching.fuzzy import EventMatcher
from moneyline.matching.review import cluster_needs_review
from moneyline.markets.spec import market_allowed_for_arb, market_spec_for
from moneyline.models.schemas import (
    ArbitrageOpportunity,
    Bookmaker,
    Event,
    MarketOdds,
    MarketPeriod,
    MatchedEvent,
    OddsOutcome,
    OutcomeSide,
    Sport,
)
from moneyline.pipeline.book_health import BookHealthTracker


def _event(book: Bookmaker, home: str, away: str, *, parent: str | None = None) -> Event:
    return Event(
        event_key=f"{book.value}:1",
        bookmaker=book,
        external_id="1",
        parent_match_id=parent,
        sport=Sport.SOCCER,
        home_team=home,
        away_team=away,
        competition="Premier League",
        start_time=datetime.now(timezone.utc) + timedelta(hours=24),
    )


def test_union_find_links_transitive_fuzzy_cluster():
    matcher = EventMatcher()
    events = [
        _event(Bookmaker.BETIKA, "Arsenal", "Chelsea"),
        _event(Bookmaker.ODIBETS, "Arsenal FC", "Chelsea FC"),
        _event(Bookmaker.SPORTPESA, "Arsenal", "Chelsea"),
    ]
    clusters = matcher.match_events(events)
    assert len(clusters) == 1
    assert len(clusters[0].events) == 3


def test_competition_alias_normalization():
    name = canonical_competition_name(Sport.SOCCER, "England Premier League")
    assert name == "premier league"


def test_market_spec_id_stable():
    market = MarketOdds(
        event_key="betika:1",
        bookmaker=Bookmaker.BETIKA,
        sport=Sport.SOCCER,
        market_key="over_under_goals",
        market_display="Over/Under Goals",
        period=MarketPeriod.FULL_TIME,
        line=2.5,
        outcomes=[
            OddsOutcome(side=OutcomeSide.OVER, label="Over", price=2.0, line=2.5),
            OddsOutcome(side=OutcomeSide.UNDER, label="Under", price=1.9, line=2.5),
        ],
        sub_type_id="18",
    )
    spec = market_spec_for(market, line=2.5)
    assert len(spec.spec_id()) == 16
    assert market_allowed_for_arb(market)


def test_blocked_combo_market_family():
    assert is_blocked_market_family("combo_1x2_ou")
    assert not is_blocked_market_family("over_under_goals")
    assert not market_allowed_for_arb(
        MarketOdds(
            event_key="betika:1",
            bookmaker=Bookmaker.BETIKA,
            sport=Sport.SOCCER,
            market_key="over_under_goals",
            market_display="1x2 & Over/Under combo",
            period=MarketPeriod.FULL_TIME,
            outcomes=[
                OddsOutcome(side=OutcomeSide.OVER, label="Over", price=2.0),
                OddsOutcome(side=OutcomeSide.UNDER, label="Under", price=1.9),
            ],
        )
    )


def test_routing_public_and_telegram_bands():
    opp_low = ArbitrageOpportunity(
        cluster_id="c1",
        sport=Sport.SOCCER,
        market_key="over_under_goals",
        market_display="O/U",
        home_team="A",
        away_team="B",
        start_time=datetime.now(timezone.utc) + timedelta(hours=1),
        margin_pct=2.5,
        implied_sum=0.97,
        legs=[{"bookmaker": "betika", "side": "over", "price": 2.1}],
    )
    opp_high = opp_low.model_copy(update={"margin_pct": 6.0})
    assert len(filter_public_feed([opp_low, opp_high])) == 1
    telegram = filter_telegram_alerts([opp_low, opp_high], deduplicate=False)
    assert len(telegram) == 1
    assert telegram[0].margin_pct == 6.0


def test_book_health_circuit_breaker(tmp_path):
    tracker = BookHealthTracker(path=tmp_path / "health.json")
    assert tracker.is_available(Bookmaker.BETIKA)
    for i in range(3):
        tracker.record_failure(Bookmaker.BETIKA, f"err {i}")
    assert not tracker.is_available(Bookmaker.BETIKA)


def test_book_health_prune_expired_cooldown(tmp_path):
    from datetime import datetime, timedelta, timezone

    tracker = BookHealthTracker(path=tmp_path / "health.json")
    for i in range(3):
        tracker.record_failure(Bookmaker.BANGBET, f"err {i}")
    assert not tracker.is_available(Bookmaker.BANGBET)
    # Simulate expired cooldown without waiting 15 minutes
    data = tracker._load()
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    data["bangbet"]["cooldown_until"] = past
    tracker._save(data)
    cleared = tracker.prune_expired_cooldowns()
    assert "bangbet" in cleared
    assert tracker.is_available(Bookmaker.BANGBET)


def test_book_health_reset(tmp_path):
    tracker = BookHealthTracker(path=tmp_path / "health.json")
    for i in range(3):
        tracker.record_failure(Bookmaker.BANGBET, "err")
    assert not tracker.is_available(Bookmaker.BANGBET)
    tracker.reset(Bookmaker.BANGBET)
    assert tracker.is_available(Bookmaker.BANGBET)


def test_review_queue_flags_low_confidence():
    cluster = MatchedEvent(
        cluster_id="fz_x",
        sport=Sport.SOCCER,
        home_team="A",
        away_team="B",
        start_time=datetime.now(timezone.utc) + timedelta(hours=1),
        teams_swapped={},
        events={Bookmaker.BETIKA: _event(Bookmaker.BETIKA, "A", "B")},
        match_confidence=0.75,
        match_confidence_kind="fuzzy_only",
    )
    assert cluster_needs_review(cluster)


def test_integer_totals_rule_loaded():
    assert reject_integer_totals_enabled() is True


def test_raw_name_blocked_patterns():
    assert raw_name_blocked("1x2 & Over/Under combo")
    assert not raw_name_blocked("Over/Under 2.5 Goals")


def test_opportunity_expires_from_odds_freshness():
    from moneyline.arb.engine import ArbitrageEngine, _opportunity_expires_at

    now = datetime.now(timezone.utc)
    fetched = now - timedelta(seconds=30)
    market = MarketOdds(
        event_key="betika:1",
        bookmaker=Bookmaker.BETIKA,
        sport=Sport.SOCCER,
        market_key="over_under_goals",
        market_display="Over/Under Goals",
        period=MarketPeriod.FULL_TIME,
        line=2.5,
        fetched_at=fetched,
        outcomes=[
            OddsOutcome(side=OutcomeSide.OVER, label="Over", price=2.0, line=2.5),
            OddsOutcome(side=OutcomeSide.UNDER, label="Under", price=1.9, line=2.5),
        ],
    )
    expires = _opportunity_expires_at([market], now=now, max_age_seconds=0)
    assert expires is None
    expires_ttl = _opportunity_expires_at([market], now=now, max_age_seconds=120)
    assert expires_ttl is not None
    assert (expires_ttl - fetched).total_seconds() == pytest.approx(120, abs=1)


def test_handshake_diagnostics_structure():
    from moneyline.pipeline.handshake import build_ops_diagnostics

    ops = build_ops_diagnostics()
    assert "book_health" in ops
    assert "match_review_count" in ops
    assert ops["architecture"]["market_spec_grouping"] is True
