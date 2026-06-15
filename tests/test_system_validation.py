"""Market-grade system validation — 20 checks for deploy readiness."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from moneyline.api.app import _scan_command_allowed, app
from moneyline.bookmakers.registry import LIVE_BOOKMAKERS
from moneyline.config.settings import get_settings
from moneyline.config_loader import get_bookmaker_config, get_bookmaker_market_workers
from moneyline.models.schemas import Bookmaker, Event, Sport
from moneyline.pipeline.collector import CollectionPipeline, market_workers_for
from moneyline.sports import SUPPORTED_SPORTS
from moneyline.storage.raw_cache import RawOddsCache
from moneyline.web.filters import filter_public_arbs, filter_premium_arbs


def test_v01_all_eight_sports_configured():
    assert len(SUPPORTED_SPORTS) == 8
    assert Sport.SOCCER in SUPPORTED_SPORTS
    assert Sport.ICE_HOCKEY in SUPPORTED_SPORTS


def test_v02_every_live_bookmaker_has_market_workers():
    for bm in LIVE_BOOKMAKERS:
        workers = get_bookmaker_market_workers(bm.value)
        assert workers >= 15, f"{bm.value} workers too low: {workers}"


def test_v03_market_workers_per_bookmaker_tuned():
    assert market_workers_for(Bookmaker.SPORTPESA) <= 25
    assert market_workers_for(Bookmaker.BETIKA) >= 40
    assert market_workers_for(Bookmaker.BANGBET) >= 35


def test_v04_bookmakers_cover_all_sports_in_config():
    for bm in LIVE_BOOKMAKERS:
        cfg = get_bookmaker_config(bm.value)
        ids = cfg.get("sport_ids") or cfg.get("sport_slugs") or {}
        supported = cfg.get("supported_sports")
        required = [s.value for s in SUPPORTED_SPORTS] if supported is None else supported
        for sport_key in required:
            assert sport_key in ids, f"{bm.value} missing {sport_key}"


def test_v05_two_phase_skips_single_book_fixtures():
    pipeline = CollectionPipeline(match_first_markets=True)
    now = datetime.now(timezone.utc)
    events = [
        Event(
            event_key="betika:1",
            bookmaker=Bookmaker.BETIKA,
            external_id="1",
            parent_match_id="br1",
            sport=Sport.SOCCER,
            home_team="A",
            away_team="B",
            start_time=now,
        ),
    ]
    assert pipeline._events_needing_markets(events) == set()


def test_v06_two_phase_includes_cross_book_fixtures():
    pipeline = CollectionPipeline(match_first_markets=True)
    now = datetime.now(timezone.utc)
    events = [
        Event(
            event_key="betika:1",
            bookmaker=Bookmaker.BETIKA,
            external_id="1",
            parent_match_id="br1",
            sport=Sport.SOCCER,
            home_team="Arsenal",
            away_team="Chelsea",
            start_time=now,
        ),
        Event(
            event_key="odibets:1",
            bookmaker=Bookmaker.ODIBETS,
            external_id="1",
            parent_match_id="br1",
            sport=Sport.SOCCER,
            home_team="Arsenal",
            away_team="Chelsea",
            start_time=now,
        ),
    ]
    needed = pipeline._events_needing_markets(events)
    assert needed == {"betika:1", "odibets:1"}


def test_v07_raw_cache_roundtrip(tmp_path):
    cache = RawOddsCache(root=tmp_path, ttl_seconds=600)
    from moneyline.models.schemas import MarketOdds, OddsOutcome, OutcomeSide

    markets = [
        MarketOdds(
            event_key="betika:1",
            bookmaker=Bookmaker.BETIKA,
            sport=Sport.SOCCER,
            market_key="match_result_1x2",
            market_display="1X2",
            outcomes=[
                OddsOutcome(side=OutcomeSide.HOME, label="1", price=2.1),
            ],
        )
    ]
    cache.put("betika", "soccer", "1", markets)
    loaded = cache.get("betika", "soccer", "1")
    assert loaded is not None
    assert loaded[0].market_key == "match_result_1x2"


def test_v08_raw_cache_respects_ttl(tmp_path):
    cache = RawOddsCache(root=tmp_path, ttl_seconds=1)
    path = cache._path("betika", "soccer", "99")
    path.parent.mkdir(parents=True, exist_ok=True)
    stale = {
        "fetched_at": (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat(),
        "markets": [],
    }
    path.write_text(json.dumps(stale), encoding="utf-8")
    assert cache.get("betika", "soccer", "99") is None


def test_v09_health_endpoint_reports_automation():
    with TestClient(app) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert len(body["supported_sports"]) == 8
    assert "match_first_markets" in body["automation"]
    assert body["automation"]["alert_min_margin_pct"] == 5.0


def test_v10_security_headers_on_responses():
    with TestClient(app) as client:
        resp = client.get("/health")
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "DENY"


def test_v11_public_api_latest_shape():
    with TestClient(app) as client:
        resp = client.get("/api/public/latest")
    assert resp.status_code == 200
    body = resp.json()
    assert body["type"] == "public_snapshot"
    assert "opportunities" in body
    assert "public_max_margin_pct" in body


def test_v12_admin_api_latest_shape():
    with TestClient(app) as client:
        resp = client.get("/api/scan/latest")
    assert resp.status_code == 200
    body = resp.json()
    assert body["type"] == "scan_snapshot"
    assert "diagnostics" in body
    assert "opportunities" in body


def test_v13_alert_margin_floor_above_five_percent():
    from moneyline.alerts.telegram import send_arbitrage_alerts
    from tests.test_telegram_format import _sample_opportunity

    low = _sample_opportunity(margin_pct=4.0)
    with patch("moneyline.alerts.telegram.send_arbitrage_alert", new_callable=AsyncMock) as mock:
        with patch("moneyline.alerts.telegram.resolve_alert_targets", return_value=["1"]):
            sent = asyncio.run(send_arbitrage_alerts([low], deduplicate=False))
    assert sent == 0
    mock.assert_not_called()


def test_v14_match_first_markets_enabled_by_default():
    get_settings.cache_clear()
    assert get_settings().match_first_markets is True


def test_v15_parallel_sport_scan_count():
    from moneyline.web.scanner import SPORT_SCAN_CONCURRENCY

    assert SPORT_SCAN_CONCURRENCY == len(SUPPORTED_SPORTS)


def test_v16_detect_arbitrage_empty_inputs():
    pipeline = CollectionPipeline()
    assert pipeline.detect_arbitrage([], []) == []


def test_v17_public_filter_caps_at_three_percent():
    from tests.test_web_filters import _opp

    opps = [_opp(2.5), _opp(4.0)]
    free = filter_public_arbs(opps, max_margin_pct=3.0)
    premium = filter_premium_arbs(opps, min_margin_pct=3.01)
    assert len(free) == 1
    assert len(premium) == 1


def test_v18_scan_command_requires_token_when_configured(monkeypatch):
    monkeypatch.setenv("WEB_ADMIN_TOKEN", "secret-scan-token")
    get_settings.cache_clear()
    assert _scan_command_allowed("scan") is False
    assert _scan_command_allowed("scan secret-scan-token") is True
    get_settings.cache_clear()


def test_v19_scan_command_open_when_no_token(monkeypatch):
    monkeypatch.setenv("WEB_ADMIN_TOKEN", "")
    get_settings.cache_clear()
    assert _scan_command_allowed("scan") is True
    get_settings.cache_clear()


def test_v20_deploy_artifacts_present():
    root = Path(__file__).resolve().parents[1]
    assert (root / "Dockerfile").is_file()
    assert (root / "render.yaml").is_file()
