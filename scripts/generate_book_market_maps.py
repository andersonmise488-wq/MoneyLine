"""Generate book_market_maps.yaml + markets.yaml sub_type updates from probe."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import yaml

from moneyline.constants import CONFIG_DIR, DATA_DIR

PROBE = DATA_DIR / "probe" / "raw_market_probe.json"
OUT_MAPS = CONFIG_DIR / "book_market_maps.yaml"


def main() -> None:
    data = json.loads(PROBE.read_text(encoding="utf-8"))
    rows = data["rows"]

    # Sport-scoped sub_type_id (sportradar family)
    sub_type: dict[str, dict[str, dict[str, str]]] = defaultdict(lambda: defaultdict(dict))
    betpawa_type: dict[str, dict[str, str]] = defaultdict(dict)
    name_aliases: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))

    for r in rows:
        if not r.get("mapped") or not r.get("canonical_key"):
            continue
        book = r["bookmaker"]
        sport = r["sport"]
        ck = r["canonical_key"]
        ids = r.get("ids") or {}
        name = (r.get("raw_name") or "").strip()
        if not name:
            continue

        st = ids.get("sub_type_id")
        if st and book in ("betika", "odibets", "pepeta"):
            sub_type[book][sport][st] = ck

        mt = ids.get("market_type_id")
        if mt and book == "betpawa":
            betpawa_type[sport][mt] = ck

        if book in ("sportybet", "bangbet", "shabiki", "mozzartbet", "sportpesa", "palmsbet"):
            name_aliases[sport][ck].add(name)

    def _plain(d: object) -> object:
        if isinstance(d, defaultdict):
            d = dict(d)
        if isinstance(d, dict):
            return {k: _plain(v) for k, v in d.items()}
        return d

    maps = _plain(
        {
            "notes": (
                "Auto-generated from scripts/generate_book_market_maps.py. "
                "Sport-scoped ID maps take precedence over name matching."
            ),
            "sportradar_sub_type_id": dict(sub_type),
            "betpawa_market_type_id": dict(betpawa_type),
        }
    )

    # Serialize name aliases suggestion (for manual merge into market_aliases.yaml)
    alias_suggest = {
        sport: {ck: sorted(names) for ck, names in sorted(cms.items())}
        for sport, cms in sorted(name_aliases.items())
    }
    maps["name_aliases_suggested"] = alias_suggest

    OUT_MAPS.write_text(yaml.safe_dump(maps, sort_keys=False, allow_unicode=True), encoding="utf-8")
    print(f"Wrote {OUT_MAPS}")
    print(f"  sportradar books: {list(sub_type.keys())}")
    print(f"  betpawa sports: {len(betpawa_type)}")
    print(f"  name alias sports: {len(alias_suggest)}")

    # Print markets.yaml sub_type_ids to add per sport/market
    markets_path = CONFIG_DIR / "markets.yaml"
    markets = yaml.safe_load(markets_path.read_text(encoding="utf-8"))
    additions: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))

    for book in ("betika", "odibets", "pepeta"):
        for sport, idmap in sub_type.get(book, {}).items():
            for sid, ck in idmap.items():
                spec = markets.get(sport, {}).get(ck)
                if not spec:
                    continue
                existing = set(str(x) for x in spec.get("betika_sub_type_ids", []))
                if sid not in existing:
                    additions[sport][ck].add(sid)

    if additions:
        print("\nSuggested betika_sub_type_ids additions:")
        for sport, mkts in sorted(additions.items()):
            for ck, sids in sorted(mkts.items()):
                print(f"  {sport}/{ck}: +{sorted(sids)}")


if __name__ == "__main__":
    main()
