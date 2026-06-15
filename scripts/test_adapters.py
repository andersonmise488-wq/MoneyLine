"""Multi-sport adapter smoke test across all live bookmakers."""

from __future__ import annotations

import asyncio
import sys

from moneyline.bookmakers.registry import LIVE_BOOKMAKERS, get_adapter
from moneyline.config_loader import get_bookmaker_config
from moneyline.models.schemas import Sport
from moneyline.pipeline.collector import ALL_SPORTS

SPORTS_TO_TEST = ALL_SPORTS


def _supports(bm, sport: Sport) -> bool:
    cfg = get_bookmaker_config(bm.value)
    ids = cfg.get("sport_ids") or cfg.get("sport_slugs") or {}
    return bool(str(ids.get(sport.value, "")).strip())


async def test_one(bm, sport: Sport) -> tuple[str, str, int, int, str]:
    if not _supports(bm, sport):
        return bm.value, sport.value, -1, -1, "skip"
    try:
        async with get_adapter(bm) as adapter:
            events = await adapter.fetch_prematch_events(sport, limit=3)
            markets = []
            if events:
                markets = await adapter.fetch_event_markets(events[0], sport)
            sample = f"{events[0].home_team} vs {events[0].away_team}" if events else "-"
            return bm.value, sport.value, len(events), len(markets), sample
    except Exception as exc:
        return bm.value, sport.value, 0, 0, f"ERROR: {exc}"


async def main() -> None:
    sport_filter = sys.argv[1:] if len(sys.argv) > 1 else None
    sports = [Sport(s) for s in sport_filter] if sport_filter else SPORTS_TO_TEST

    print(f"{'Bookmaker':<12} {'Sport':<14} {'Ev':>3} {'Mk':>3}  Sample")
    print("-" * 72)
    for sport in sports:
        for bm in sorted(LIVE_BOOKMAKERS, key=lambda x: x.value):
            name, sp, ev, mk, sample = await test_one(bm, sport)
            if ev == -1:
                continue
            print(f"{name:<12} {sp:<14} {ev:>3} {mk:>3}  {sample[:40]}")


if __name__ == "__main__":
    asyncio.run(main())
