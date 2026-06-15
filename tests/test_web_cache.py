from __future__ import annotations

from datetime import datetime, timezone

from moneyline.models.schemas import ArbitrageOpportunity, Sport
from moneyline.web.cache import ScanCache


def _sample_opp(margin: float = 4.5) -> ArbitrageOpportunity:
    now = datetime.now(timezone.utc)
    return ArbitrageOpportunity(
        cluster_id="c1",
        sport=Sport.SOCCER,
        market_key="1x2",
        market_display="1X2",
        home_team="Team A",
        away_team="Team B",
        start_time=now,
        margin_pct=margin,
        implied_sum=0.96,
        legs=[],
    )


def test_scan_cache_roundtrip(tmp_path, monkeypatch) -> None:
    cache_file = tmp_path / "arbs_latest.json"
    monkeypatch.setattr("moneyline.web.cache.CACHE_FILE", cache_file)
    monkeypatch.setattr("moneyline.web.cache.CACHE_DIR", tmp_path)

    now = datetime.now(timezone.utc)
    opps = [_sample_opp()]
    ScanCache.save(opps, scanned_at=now, min_margin_pct=3.0)

    loaded = ScanCache.load()
    assert loaded.total == 1
    assert loaded.opportunities[0].margin_pct == 4.5
    assert loaded.scanned_at is not None


def test_scan_cache_is_stale() -> None:
    old = datetime.now(timezone.utc)
    assert ScanCache.is_stale(None, 10) is True
    assert ScanCache.is_stale(old, 9999) is False
