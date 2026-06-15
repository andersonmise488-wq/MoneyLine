import asyncio

from moneyline.bookmakers.mozzartbet import MozzartBetAdapter
from moneyline.models.schemas import Sport


def test_mozzartbet_failing_match_no_crash():
    async def _run():
        async with MozzartBetAdapter() as ad:
            events = await ad.fetch_prematch_events(Sport.SOCCER, limit=3)
            assert events
            mkts = await ad.fetch_event_markets(events[0], Sport.SOCCER)
            return len(mkts)

    assert asyncio.run(_run()) >= 1
