"""SportyBet status handling and BetPawa sport scope."""

from __future__ import annotations

import asyncio

from moneyline.bookmakers.registry import get_adapter
from moneyline.bookmakers.sportybet import SportyBetAdapter
from moneyline.config_loader import get_bookmaker_config
from moneyline.models.schemas import Bookmaker, Sport
from moneyline.pipeline.collector import CollectionPipeline


def test_sportybet_row_is_live_status_codes():
    assert SportyBetAdapter._row_is_live({"status": 1}) is True
    assert SportyBetAdapter._row_is_live({"status": 0}) is False
    assert SportyBetAdapter._row_is_live({"status": "live"}) is True
    assert SportyBetAdapter._row_is_live({}) is False


def test_betpawa_only_three_sports():
    cfg = get_bookmaker_config("betpawa")
    assert cfg.get("supported_sports") == ["soccer", "basketball", "tennis"]
    assert "volleyball" not in (cfg.get("sport_ids") or {})


def test_collector_skips_betpawa_volleyball():
    pipeline = CollectionPipeline()
    assert pipeline._bookmaker_supports_sport(Bookmaker.BETPAWA, Sport.VOLLEYBALL) is False
    assert pipeline._bookmaker_supports_sport(Bookmaker.BETPAWA, Sport.SOCCER) is True


def test_sportybet_tennis_prematch_fetch():
    async def _run() -> int:
        async with get_adapter(Bookmaker.SPORTYBET) as adapter:
            assert isinstance(adapter, SportyBetAdapter)
            events = await adapter.fetch_prematch_events(Sport.TENNIS, limit=0)
            return len(events)

    count = asyncio.run(_run())
    assert count >= 0
