from __future__ import annotations

from datetime import datetime, timedelta, timezone

from moneyline.models.schemas import ArbitrageOpportunity, Sport
from moneyline.ops.arb_validation import margin_math_ok, recalc_margin_from_legs, summarize_checks
from moneyline.ops.arb_validation import OpportunityCheckResult
from moneyline.pipeline.collector import CollectionPipeline
from moneyline.web.cache import ScanSnapshot


def _opp(price_home: float = 2.1, price_away: float = 2.2) -> ArbitrageOpportunity:
    now = datetime.now(timezone.utc)
    legs = [
        {"bookmaker": "betika", "side": "home", "label": "1", "price": price_home, "event_key": "betika:1"},
        {"bookmaker": "odibets", "side": "away", "label": "2", "price": price_away, "event_key": "odibets:1"},
    ]
    implied_sum, margin_pct = recalc_margin_from_legs(legs)
    return ArbitrageOpportunity(
        cluster_id="c1",
        sport=Sport.SOCCER,
        market_key="match_result_1x2",
        market_display="1X2",
        home_team="Team A",
        away_team="Team B",
        start_time=now + timedelta(hours=24),
        margin_pct=margin_pct,
        implied_sum=implied_sum,
        legs=legs,
        fixture_id="fx1",
        match_confidence=0.95,
    )


def test_margin_recalc_matches_engine() -> None:
    opp = _opp(price_home=2.1, price_away=2.2)
    assert opp.margin_pct > 0
    assert margin_math_ok(opp)


def test_unrealistic_margin_flagged_in_summary() -> None:
    opp = _opp(price_home=1.5, price_away=1.5)  # negative margin, use manual unrealistic
    results = [
        OpportunityCheckResult(
            opportunity_id="x",
            sport="soccer",
            home_team="A",
            away_team="B",
            market_key="match_result_1x2",
            margin_reported=25.0,
            margin_recalc=25.0,
            margin_ok=True,
            realistic=False,
            match_confidence=0.9,
            ok=False,
            issues=["suspicious"],
        )
    ]
    summary = summarize_checks(results)
    assert summary["unrealistic_margin"] == 1
    assert summary["passed"] == 0


def test_collector_has_no_margin_cap() -> None:
    pipeline = CollectionPipeline(min_margin_pct=0.0)
    assert pipeline.arb_engine.max_margin_pct is None


def test_scan_snapshot_roundtrip() -> None:
    opp = _opp()
    snap = ScanSnapshot(
        opportunities=[opp],
        scanned_at=datetime.now(timezone.utc),
        scanning=False,
        error=None,
        min_margin_pct=0.0,
        max_events=0,
        max_markets=0,
    )
    assert snap.total == 1
    assert snap.opportunities[0].margin_pct == opp.margin_pct
