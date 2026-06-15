"""Merge probe-discovered sub_type_ids into config/markets.yaml."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import yaml

from moneyline.constants import CONFIG_DIR, DATA_DIR

PROBE = DATA_DIR / "probe" / "raw_market_probe.json"
MARKETS = CONFIG_DIR / "markets.yaml"


def main() -> None:
    data = json.loads(PROBE.read_text(encoding="utf-8"))
    additions: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))

    for r in data["rows"]:
        if not r.get("mapped") or not r.get("canonical_key"):
            continue
        if r["bookmaker"] not in ("betika", "odibets", "pepeta"):
            continue
        st = (r.get("ids") or {}).get("sub_type_id")
        if not st:
            continue
        sport = r["sport"]
        ck = r["canonical_key"]
        additions[sport][ck].add(str(st))

    markets = yaml.safe_load(MARKETS.read_text(encoding="utf-8"))
    changed = 0
    for sport, mkts in additions.items():
        for ck, sids in mkts.items():
            spec = markets.get(sport, {}).get(ck)
            if not spec:
                continue
            existing = {str(x) for x in spec.get("betika_sub_type_ids", [])}
            new_ids = sorted(existing | sids)
            if new_ids != sorted(existing):
                spec["betika_sub_type_ids"] = new_ids
                changed += 1
                print(f"  {sport}/{ck}: {sorted(existing)} -> {new_ids}")

    if changed:
        MARKETS.write_text(yaml.safe_dump(markets, sort_keys=False, allow_unicode=True), encoding="utf-8")
        print(f"Updated {changed} market specs in {MARKETS}")
    else:
        print("No markets.yaml changes needed")


if __name__ == "__main__":
    main()
