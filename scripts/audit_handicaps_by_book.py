"""Count handicap markets captured per bookmaker (soccer sample)."""
from __future__ import annotations

import asyncio
from collections import Counter, defaultdict

from moneyline.bookmakers.registry import LIVE_BOOKMAKERS, get_adapter
from moneyline.models.schemas import Bookmaker, Sport

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
    sport = Sport.SOCCER
    print(f"Handicap capture audit — {sport.value}\n")
    raw_unmapped: dict[str, list[str]] = defaultdict(list)

    for bm in sorted(LIVE_BOOKMAKERS, key=lambda b: b.value):
        adapter = get_adapter(bm)
        hc: Counter[str] = Counter()
        try:
            async with adapter:
                events = await adapter.fetch_prematch_events(sport, limit=15)
                for ev in events[:10]:
                    mkts = await adapter.fetch_event_markets(ev, sport)
                    for m in mkts:
                        if m.market_key in HANDICAP_KEYS:
                            hc[m.market_key] += 1
                        elif m.raw_market_name and "handicap" in m.raw_market_name.lower():
                            raw_unmapped[bm.value].append(m.raw_market_name)
        except Exception as exc:
            print(f"{bm.value:12} ERROR {exc}")
            continue
        total = sum(hc.values())
        print(f"{bm.value:12} total={total:4}  {dict(hc)}")

    if raw_unmapped:
        print("\nUnmapped handicap-like raw names (sample):")
        for bm, names in raw_unmapped.items():
            uniq = sorted(set(names))[:5]
            if uniq:
                print(f"  {bm}: {uniq}")


if __name__ == "__main__":
    asyncio.run(main())
