from __future__ import annotations

from datetime import datetime, timedelta, timezone

from moneyline.alerts.dedup import AlertDedupStore
from moneyline.arb.identity import merge_active_opportunities, opportunity_fingerprint, opportunity_id
from moneyline.models.schemas import ArbitrageOpportunity, Sport


def _opp(
    *,
    margin: float = 4.0,
    cluster_id: str = "c1",
    fixture_id: str = "fx1",
    market_key: str = "1x2",
    line: float | None = None,
    price: float = 2.0,
    detected_at: datetime | None = None,
    start_offset_hours: float = 24,
) -> ArbitrageOpportunity:
    now = datetime.now(timezone.utc)
    return ArbitrageOpportunity(
        cluster_id=cluster_id,
        sport=Sport.SOCCER,
        market_key=market_key,
        market_display="1X2",
        home_team="A",
        away_team="B",
        start_time=now + timedelta(hours=start_offset_hours),
        margin_pct=margin,
        implied_sum=0.97,
        line=line,
        legs=[{"bookmaker": "betika", "side": "home", "label": "A", "price": price}],
        detected_at=detected_at or now,
        fixture_id=fixture_id,
    )


def test_opportunity_id_stable() -> None:
    opp = _opp()
    assert opportunity_id(opp) == opportunity_id(opp)


def test_fingerprint_changes_with_price() -> None:
    a = _opp(price=2.0)
    b = _opp(price=2.1)
    assert opportunity_fingerprint(a) != opportunity_fingerprint(b)


def test_merge_keeps_active_missing_from_fresh_scan() -> None:
    now = datetime.now(timezone.utc)
    existing = [_opp(margin=5.0, detected_at=now - timedelta(minutes=5))]
    merged = merge_active_opportunities(existing, [], now=now, grace_minutes=20)
    assert len(merged) == 1


def test_merge_drops_started_fixtures() -> None:
    now = datetime.now(timezone.utc)
    existing = [_opp(start_offset_hours=-1, detected_at=now - timedelta(minutes=5))]
    merged = merge_active_opportunities(existing, [], now=now, grace_minutes=20)
    assert merged == []


def test_dedup_blocks_repeat_within_hour(tmp_path) -> None:
    store = AlertDedupStore(path=tmp_path / "dedup.json", cooldown_minutes=60)
    opp = _opp()
    assert store.should_send(opp) is True
    store.mark_sent(opp)
    assert store.should_send(opp) is False


def test_dedup_resends_when_fingerprint_changes(tmp_path) -> None:
    store = AlertDedupStore(path=tmp_path / "dedup.json", cooldown_minutes=60)
    first = _opp(price=2.0)
    store.mark_sent(first)
    changed = _opp(price=2.2)
    assert store.should_send(changed) is True
