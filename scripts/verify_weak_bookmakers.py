"""Verify weak bookmaker coverage after fixes."""
from __future__ import annotations

import asyncio

from moneyline.bookmakers.registry import LIVE_BOOKMAKERS, get_adapter
from moneyline.constants import EVENT_LOOKAHEAD_HOURS
from moneyline.models.schemas import Bookmaker, Sport
from moneyline.timezone import as_utc


TARGETS = {
    Bookmaker.ODIBETS,
    Bookmaker.SPORTYBET,
    Bookmaker.SHABIKI,
    Bookmaker.BETIKA,
}


async def main() -> None:
    print(f"Window: {EVENT_LOOKAHEAD_HOURS}h | sport=soccer | limit=0\n")
    for bm in sorted(TARGETS, key=lambda b: b.value):
        async with get_adapter(bm) as adapter:
            events = await adapter.fetch_prematch_events(
                Sport.SOCCER, limit=0, lookahead_hours=EVENT_LOOKAHEAD_HOURS
            )
        if not events:
            print(f"{bm.value:12} 0 events")
            continue
        starts = [as_utc(e.start_time) for e in events]
        print(
            f"{bm.value:12} {len(events):4} events  "
            f"earliest={min(starts).strftime('%m-%d %H:%M')}  "
            f"latest={max(starts).strftime('%m-%d %H:%M')}"
        )


if __name__ == "__main__":
    asyncio.run(main())
