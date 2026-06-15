"""Two-phase collection behavior."""

from __future__ import annotations

from datetime import datetime, timezone

from moneyline.models.schemas import Bookmaker, Event, Sport
from moneyline.pipeline.collector import CollectionPipeline


def test_match_first_off_fetches_all_event_keys():
    pipeline = CollectionPipeline(match_first_markets=False)
    now = datetime.now(timezone.utc)
    events = [
        Event(
            event_key="betika:solo",
            bookmaker=Bookmaker.BETIKA,
            external_id="solo",
            sport=Sport.SOCCER,
            home_team="X",
            away_team="Y",
            start_time=now,
        )
    ]
    assert pipeline._events_needing_markets(events) == {"betika:solo"}


def test_market_workers_respects_bookmaker_config():
    from moneyline.pipeline.collector import market_workers_for

    assert market_workers_for(Bookmaker.BETIKA) >= 40
