"""Deep coverage audit: events, markets, matching, and arb potential."""
from __future__ import annotations

import asyncio
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from moneyline.arb.engine import ArbitrageEngine, arb_margin
from moneyline.bookmakers.registry import LIVE_BOOKMAKERS
from moneyline.constants import EVENT_LOOKAHEAD_HOURS
from moneyline.models.schemas import Sport
from moneyline.pipeline.collector import ALL_SPORTS, CollectionPipeline
from moneyline.web.scanner import _best_cross_book_margin


async def audit_limits(max_events: int, max_market_fetches: int) -> dict:
    pipeline = CollectionPipeline(
        min_margin_pct=0,
        max_events=max_events,
        max_market_fetches=max_market_fetches,
        lookahead_hours=EVENT_LOOKAHEAD_HOURS,
    )
    engine = ArbitrageEngine(min_margin_pct=0)

    totals = {
        "events": 0,
        "markets": 0,
        "events_with_markets": 0,
        "clusters": 0,
        "clusters_2plus_bookies": 0,
        "clusters_3plus_bookies": 0,
        "opps_0pct": 0,
        "best_margin": None,
        "by_bookmaker_events": Counter(),
        "by_bookmaker_markets": Counter(),
        "cluster_size_hist": Counter(),
    }

    for sport in ALL_SPORTS:
        events, markets = await pipeline.collect_sport(sport)
        totals["events"] += len(events)
        totals["markets"] += len(markets)

        events_with_mkts = {m.event_key for m in markets}
        totals["events_with_markets"] += len(events_with_mkts)

        for ev in events:
            totals["by_bookmaker_events"][ev.bookmaker.value] += 1
        for m in markets:
            totals["by_bookmaker_markets"][m.bookmaker.value] += 1

        clusters = pipeline.matcher.match_events(events)
        totals["clusters"] += len(clusters)
        markets_by_event: dict[str, list] = defaultdict(list)
        for m in markets:
            markets_by_event[m.event_key].append(m)

        for cluster in clusters:
            n = len(cluster.events)
            totals["cluster_size_hist"][n] += 1
            if n >= 2:
                totals["clusters_2plus_bookies"] += 1
            if n >= 3:
                totals["clusters_3plus_bookies"] += 1
            best = _best_cross_book_margin([cluster], markets_by_event, engine)
            if best and (totals["best_margin"] is None or best[0] > totals["best_margin"]):
                totals["best_margin"] = best[0]

        opps = pipeline.detect_arbitrage(events, markets)
        totals["opps_0pct"] += len(opps)

    return totals


async def main() -> None:
    print("=== MoneyLine coverage audit ===")
    print(f"Bookmakers: {len(LIVE_BOOKMAKERS)} | Sports: {len(ALL_SPORTS)} | Window: {EVENT_LOOKAHEAD_HOURS}h\n")

    configs = [
        ("Old capped scan (20 events, 10 market-fetches)", 20, 10),
        ("Full window (unlimited events + markets)", 0, 0),
        ("Deep capped scan (50 events, 50 market-fetches)", 50, 50),
    ]

    for label, ev_limit, mk_limit in configs:
        print(f"--- {label} ---")
        t = await audit_limits(ev_limit, mk_limit)
        pct_with_markets = (
            100 * t["events_with_markets"] / t["events"] if t["events"] else 0
        )
        print(f"  Events collected:     {t['events']:,}")
        print(f"  Events with markets:    {t['events_with_markets']:,} ({pct_with_markets:.0f}%)")
        print(f"  Markets collected:      {t['markets']:,}")
        print(f"  Matched clusters:       {t['clusters']:,}")
        print(f"  Clusters 2+ bookmakers: {t['clusters_2plus_bookies']:,}")
        print(f"  Clusters 3+ bookmakers: {t['clusters_3plus_bookies']:,}")
        print(f"  Arbs found (0% min):    {t['opps_0pct']:,}")
        print(f"  Best cross-book margin: {t['best_margin']:.2f}%" if t['best_margin'] is not None else "  Best cross-book margin: n/a")
        print(f"  Cluster sizes:          {dict(sorted(t['cluster_size_hist'].items()))}")
        print()

    print("--- Events per bookmaker (deep scan) ---")
    t = await audit_limits(50, 50)
    for bm in sorted(LIVE_BOOKMAKERS, key=lambda b: b.value):
        evs = t["by_bookmaker_events"][bm.value]
        mks = t["by_bookmaker_markets"][bm.value]
        print(f"  {bm.value:12} {evs:4} events  {mks:5} markets")

    print("\nNOTE: max_market_fetches limits how many EVENTS get market API calls,")
    print("      not markets per event. Use 0 / None to fetch markets for all events.")


if __name__ == "__main__":
    asyncio.run(main())
