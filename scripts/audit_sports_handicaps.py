"""Quick audit: all sports, handicap capture, arb counts."""
from __future__ import annotations

import asyncio
from collections import Counter

from moneyline.constants import EVENT_LOOKAHEAD_HOURS
from moneyline.models.schemas import Sport
from moneyline.pipeline.collector import CollectionPipeline

HANDICAP_KEYS = {
    "asian_handicap",
    "european_handicap",
    "spread",
    "game_handicap",
    "set_handicap",
    "run_line",
    "puck_line",
}


async def main() -> None:
    pipe = CollectionPipeline(
        max_events=80,
        max_market_fetches=40,
        lookahead_hours=EVENT_LOOKAHEAD_HOURS,
    )
    print(f"{'Sport':<14} {'Evts':>5} {'Mkts':>6} {'Clu':>4} {'Arbs':>4}  Handicaps")
    print("-" * 72)
    sport_arbs: dict[str, int] = {}
    for sport in Sport:
        events, markets = await pipe.collect_sport(sport)
        clusters = pipe.matcher.match_events(events)
        opps = pipe.detect_arbitrage(events, markets)
        sport_arbs[sport.value] = len(opps)
        hc = Counter(
            m.market_key
            for m in markets
            if m.market_key in HANDICAP_KEYS
            or "handicap" in (m.raw_market_name or "").lower()
        )
        euro = sorted(
            {
                m.raw_market_name
                for m in markets
                if m.raw_market_name and "european" in m.raw_market_name.lower()
            }
        )
        print(
            f"{sport.value:<14} {len(events):>5,} {len(markets):>6,} "
            f"{len(clusters):>4} {len(opps):>4}  {dict(hc)}"
        )
        for name in euro[:3]:
            print(f"    european raw: {name}")
    print("\nArbs by sport:", sport_arbs)


if __name__ == "__main__":
    asyncio.run(main())
