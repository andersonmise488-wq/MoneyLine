"""Find book×sport gaps: configured sport but zero prematch events/markets in 72h window."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from moneyline.bookmakers.registry import LIVE_BOOKMAKERS, get_adapter
from moneyline.config_loader import get_bookmaker_config
from moneyline.constants import EVENT_LOOKAHEAD_HOURS
from moneyline.models.schemas import Sport
from moneyline.sports import SUPPORTED_SPORTS


def _supported(book: str, sport: Sport) -> bool:
    cfg = get_bookmaker_config(book)
    listed = cfg.get("supported_sports")
    if listed is not None:
        return sport.value in listed
    ids = cfg.get("sport_ids") or cfg.get("sport_slugs") or {}
    return bool(str(ids.get(sport.value, "")).strip())


async def main() -> None:
    gaps: list[tuple[str, str, int, int]] = []
    print(f"Window: {EVENT_LOOKAHEAD_HOURS}h (prematch only)\n")
    for bm in sorted(LIVE_BOOKMAKERS, key=lambda b: b.value):
        for sport in SUPPORTED_SPORTS:
            if not _supported(bm.value, sport):
                continue
            try:
                async with get_adapter(bm) as ad:
                    events = await ad.fetch_prematch_events(
                        sport, limit=0, lookahead_hours=EVENT_LOOKAHEAD_HOURS
                    )
                    mkts = 0
                    if events:
                        sample = events[: min(3, len(events))]
                        for ev in sample:
                            batch = await ad.fetch_event_markets(ev, sport)
                            mkts += len(batch)
            except Exception as exc:
                print(f"{bm.value:12} {sport.value:12} ERROR {exc}")
                gaps.append((bm.value, sport.value, -1, -1))
                continue
            if len(events) == 0 or mkts == 0:
                gaps.append((bm.value, sport.value, len(events), mkts))
            print(f"{bm.value:12} {sport.value:12} ev={len(events):4} sample_mkts={mkts}")

    print("\n=== GAPS (0 events or 0 sample markets) ===")
    for book, sport, ev, mk in gaps:
        print(f"  {book:12} {sport:12} events={ev} sample_mkts={mk}")


if __name__ == "__main__":
    asyncio.run(main())
