"""Test Odibets inline prematch markets fallback."""
import asyncio

from moneyline.bookmakers.odibets import OdibetsAdapter
from moneyline.models.schemas import Sport


def test_outcomes_from_inline_row():
    row = {
        "sub_type_id": "186",
        "odd_type": "Winner",
        "outcomes": [
            {"outcome_id": "4", "outcome_key": "1", "outcome_name": "A", "odd_value": "2.0"},
            {"outcome_id": "5", "outcome_key": "2", "outcome_name": "B", "odd_value": "1.8"},
        ],
    }
    outs = OdibetsAdapter._outcomes_from_market_row(row)
    assert len(outs) == 2


def test_odibets_tennis_markets_from_inline():
    async def _run():
        async with OdibetsAdapter() as ad:
            evs = await ad.fetch_prematch_events(Sport.TENNIS, limit=5)
            with_mkts = 0
            for e in evs:
                mkts = await ad.fetch_event_markets(e, Sport.TENNIS)
                if mkts:
                    with_mkts += 1
            return with_mkts

    assert asyncio.run(_run()) >= 1
