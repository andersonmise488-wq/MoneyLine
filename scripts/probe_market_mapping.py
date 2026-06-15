"""Audit canonical market mapping: collisions, unmapped labels, settlement splits."""
from __future__ import annotations

import asyncio
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from moneyline.constants import DATA_DIR
from moneyline.markets.registry import MarketRegistry
from moneyline.markets.resolve import market_resolution_priority
from moneyline.models.schemas import Sport
from scripts.probe_raw_markets import _probe_adapter, _summarize, _supports_sport, _unique_rows, SPORTS

from moneyline.bookmakers.registry import LIVE_BOOKMAKERS


def audit_registry_collisions() -> list[dict]:
    reg = MarketRegistry()
    by_name: dict[tuple[str, str], list[str]] = defaultdict(list)
    for (sport, name), (market_key, _) in reg._exact.items():
        by_name[(sport.value, name)].append(market_key)
    collisions = []
    for key, keys in by_name.items():
        unique = sorted(set(keys))
        if len(unique) > 1:
            winner = min(unique, key=market_resolution_priority)
            collisions.append(
                {"sport": key[0], "alias": key[1], "keys": unique, "registry_winner": winner}
            )
    return collisions


async def main() -> None:
    collisions = audit_registry_collisions()
    rows = []
    for book in sorted(LIVE_BOOKMAKERS, key=lambda b: b.value):
        for sport in SPORTS:
            if not _supports_sport(book, sport):
                continue
            print(f"Probing {book.value}/{sport.value}...")
            rows.extend(await _probe_adapter(book, sport))
    rows = _unique_rows(rows)
    summary = _summarize(rows)
    out = {
        "registry_alias_collisions": collisions,
        "probe_summary": summary,
    }
    path = DATA_DIR / "probe" / "market_mapping_audit.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\nWrote {path}")
    print(f"Registry alias collisions: {len(collisions)}")
    print(f"Unmapped raw labels: {summary['unmapped_count']}")
    print(f"Mapped: {summary['mapped_raw']}/{summary['total_raw']}")


if __name__ == "__main__":
    asyncio.run(main())
