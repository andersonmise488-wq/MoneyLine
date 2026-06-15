import asyncio
from moneyline.bookmakers.registry import LIVE_BOOKMAKERS, get_adapter
from moneyline.constants import EVENT_LOOKAHEAD_HOURS
from moneyline.events.window import window_bounds, as_utc
from moneyline.models.schemas import Sport


async def main() -> None:
    lower, upper = window_bounds()
    print(f"Window: {lower.isoformat()} -> {upper.isoformat()} ({EVENT_LOOKAHEAD_HOURS}h)")
    for bm in sorted(LIVE_BOOKMAKERS, key=lambda x: x.value):
        async with get_adapter(bm) as adapter:
            events = await adapter.fetch_prematch_events(
                Sport.SOCCER, limit=0, lookahead_hours=EVENT_LOOKAHEAD_HOURS
            )
        if not events:
            print(f"{bm.value:12} 0 events")
            continue
        starts = [as_utc(e.start_time) for e in events]
        print(
            f"{bm.value:12} {len(events):3} events  "
            f"earliest={min(starts).strftime('%m-%d %H:%M')}  "
            f"latest={max(starts).strftime('%m-%d %H:%M')}"
        )


if __name__ == "__main__":
    asyncio.run(main())
