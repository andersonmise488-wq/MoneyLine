"""End-to-end arb validation: scan sample sports, verify margins vs live API, check API feed parity."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from moneyline.constants import DATA_DIR
from moneyline.models.schemas import Sport
from moneyline.ops.arb_validation import summarize_checks, validate_opportunities
from moneyline.pipeline.collector import CollectionPipeline
from moneyline.web.cache import ScanCache

OUTPUT = DATA_DIR / "probe" / "arb_e2e_validation.json"

SAMPLE_SPORTS = [Sport.SOCCER, Sport.TENNIS]
EVENT_LIMIT = 80
MARKET_LIMIT = 150


async def scan_and_validate() -> dict:
    pipeline = CollectionPipeline(max_events=EVENT_LIMIT, max_market_fetches=MARKET_LIMIT)
    all_events: list = []
    all_markets: list = []
    all_opps: list = []

    for sport in SAMPLE_SPORTS:
        print(f"Collecting {sport.value} (limit {EVENT_LIMIT} events)...")
        events, markets = await pipeline.collect_sport(sport)
        opps = pipeline.detect_arbitrage(events, markets)
        print(f"  {sport.value}: {len(events)} events, {len(markets)} markets, {len(opps)} arbs")
        all_events.extend(events)
        all_markets.extend(markets)
        all_opps.extend(opps)

    print(f"\nValidating top opportunities (live API cross-check)...")
    checks = await validate_opportunities(
        all_opps,
        events=all_events,
        verify_live=True,
        max_checks=20,
        price_tolerance=0.08,
    )
    summary = summarize_checks(checks)
    return {
        "sports": [s.value for s in SAMPLE_SPORTS],
        "event_limit": EVENT_LIMIT,
        "market_limit": MARKET_LIMIT,
        "max_margin_cap": None,
        "opportunities_found": len(all_opps),
        "validation_summary": summary,
        "checks": [
            {
                "id": c.opportunity_id,
                "sport": c.sport,
                "match": f"{c.home_team} vs {c.away_team}",
                "market_key": c.market_key,
                "margin_reported": c.margin_reported,
                "margin_recalc": round(c.margin_recalc, 3),
                "margin_ok": c.margin_ok,
                "realistic": c.realistic,
                "match_confidence": c.match_confidence,
                "ok": c.ok,
                "issues": c.issues,
                "legs": [
                    {
                        "bookmaker": leg.bookmaker,
                        "reported": leg.reported_price,
                        "live": leg.live_price,
                        "ok": leg.ok,
                        "detail": leg.detail,
                    }
                    for leg in c.legs
                ],
            }
            for c in checks
        ],
    }


def compare_api_feed() -> dict:
    """Compare REST scan cache with local ScanCache (server must be running)."""
    import urllib.request

    try:
        with urllib.request.urlopen("http://localhost:8080/api/scan/latest", timeout=10) as resp:
            api_payload = json.loads(resp.read().decode())
    except Exception as exc:
        return {"api_reachable": False, "error": str(exc)}

    snapshot = ScanCache.load()
    api_total = int(api_payload.get("total", 0))
    cache_total = len(snapshot.opportunities)
    api_scanning = bool(api_payload.get("scanning"))
    cache_scanning = snapshot.scanning
    return {
        "api_reachable": True,
        "api_total": api_total,
        "cache_total": cache_total,
        "totals_match": api_total == cache_total,
        "api_scanning": api_scanning,
        "cache_scanning": cache_scanning,
        "api_scanned_at": api_payload.get("scanned_at"),
        "cache_scanned_at": snapshot.scanned_at.isoformat() if snapshot.scanned_at else None,
    }


async def main() -> None:
    report = await scan_and_validate()
    report["api_feed_parity"] = compare_api_feed()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nWrote {OUTPUT}")
    vs = report["validation_summary"]
    print(
        f"Validation: {vs['passed']}/{vs['checked']} passed "
        f"({vs['pass_rate_pct']}%) | unrealistic: {vs['unrealistic_margin']} | "
        f"live_fail: {vs['live_api_fail']}"
    )
    ap = report["api_feed_parity"]
    if ap.get("api_reachable"):
        print(
            f"API feed: total={ap['api_total']} cache={ap['cache_total']} "
            f"match={ap['totals_match']} scanning={ap['api_scanning']}"
        )
    else:
        print(f"API feed: not reachable ({ap.get('error')})")

    if vs["failed"] > 0 or vs["unrealistic_margin"] > 0:
        print("\nFAILED checks:")
        for row in report["checks"]:
            if not row["ok"]:
                print(f"  - {row['match']} [{row['market_key']}] margin={row['margin_reported']:.2f}%")
                for issue in row["issues"]:
                    print(f"      {issue}")


if __name__ == "__main__":
    asyncio.run(main())
