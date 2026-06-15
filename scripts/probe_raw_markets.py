"""Deep probe: raw market names/IDs per bookmaker × sport for canonical mapping."""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from moneyline.config_loader import get_bookmaker_config
from moneyline.constants import DATA_DIR
from moneyline.markets.name_mapper import NameMarketMapper
from moneyline.markets.normalizer import MarketNormalizer
from moneyline.models.schemas import Bookmaker, Sport
from moneyline.sports import SUPPORTED_SPORTS

OUTPUT = DATA_DIR / "probe" / "raw_market_probe.json"

SPORTS = [Sport(s) for s in SUPPORTED_SPORTS]


def _supports_sport(book: Bookmaker, sport: Sport) -> bool:
    cfg = get_bookmaker_config(book.value)
    supported = cfg.get("supported_sports")
    if supported:
        return sport.value in supported
    ids = cfg.get("sport_ids") or cfg.get("sport_slugs") or {}
    return sport.value in ids


@dataclass
class RawMarketRow:
    bookmaker: str
    sport: str
    event_id: str
    raw_name: str
    canonical_key: str | None
    mapped: bool
    ids: dict[str, str] = field(default_factory=dict)
    sample_outcomes: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


def _unique_rows(rows: list[RawMarketRow]) -> list[RawMarketRow]:
    seen: set[tuple] = set()
    out: list[RawMarketRow] = []
    for row in rows:
        key = (row.bookmaker, row.sport, row.raw_name, tuple(sorted(row.ids.items())))
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


async def _probe_adapter(book: Bookmaker, sport: Sport) -> list[RawMarketRow]:
    from moneyline.bookmakers.registry import get_adapter

    mapper = NameMarketMapper()
    normalizer = MarketNormalizer()
    rows: list[RawMarketRow] = []

    try:
        async with get_adapter(book) as adapter:
            events = await adapter.fetch_prematch_events(sport, limit=1)
            if not events:
                return rows
            event = events[0]
            markets = await adapter.fetch_event_markets(event, sport)
            normalized_names = {m.raw_market_name or m.market_display: m.market_key for m in markets}

            # Re-fetch raw depending on book type
            raw_markets = await _fetch_raw_markets(adapter, book, event, sport)
            for raw in raw_markets:
                name = raw["name"]
                hit = mapper.resolve(sport, name)
                canonical = hit[0] if hit else None
                ids = raw.get("ids") or {}
                sub_id = str(raw.get("sub_type_id") or ids.get("sub_type_id") or "")
                if not hit and sub_id:
                    hit = normalizer._betika_index.get((sport, sub_id))
                    if hit:
                        canonical = hit[0]
                rows.append(
                    RawMarketRow(
                        bookmaker=book.value,
                        sport=sport.value,
                        event_id=event.external_id,
                        raw_name=name,
                        canonical_key=canonical,
                        mapped=canonical is not None,
                        ids=raw.get("ids", {}),
                        sample_outcomes=raw.get("outcomes", [])[:4],
                        extra=raw.get("extra", {}),
                    )
                )
                # Track if normalized adapter got it but name probe didn't
                if name in normalized_names and not canonical:
                    rows[-1].canonical_key = normalized_names[name]
                    rows[-1].mapped = True
    except Exception as exc:
        rows.append(
            RawMarketRow(
                bookmaker=book.value,
                sport=sport.value,
                event_id="",
                raw_name=f"__ERROR__:{exc}",
                canonical_key=None,
                mapped=False,
            )
        )
    return rows


async def _fetch_raw_markets(adapter: Any, book: Bookmaker, event: Any, sport: Sport) -> list[dict]:
    """Return list of {name, ids, outcomes, extra} from raw API payloads."""
    rows: list[dict] = []

    if book in (Bookmaker.BETIKA, Bookmaker.PEPETA):
        parent = event.parent_match_id or event.external_id
        url = adapter._resolve_url(
            adapter.config["endpoints"]["match_markets"].format(parent_match_id=parent)
        )
        payload = (await adapter._get(url)).json()
        for mkt in payload.get("data", []) or []:
            name = str(mkt.get("name", ""))
            ocs = mkt.get("odds") or []
            rows.append(
                {
                    "name": name,
                    "ids": {"sub_type_id": str(mkt.get("sub_type_id", ""))},
                    "outcomes": [str(o.get("display") or o.get("odd_key", "")) for o in ocs[:4]],
                    "extra": {"market_keys": list(mkt.keys())[:12]},
                }
            )
        return rows

    if book == Bookmaker.ODIBETS:
        url = adapter.config["endpoints"]["match_markets"].split()[1]
        if not url.startswith("http"):
            url = f"{adapter.config['match_url']}{url}"
        body = {"id": event.parent_match_id or event.external_id, "sub_type_id": ""}
        payload = (await adapter._post(url, json=body)).json()
        for mkt in payload.get("data", {}).get("markets", []) or []:
            name = str(mkt.get("odd_type") or mkt.get("name") or "")
            ocs = []
            for line in mkt.get("lines") or []:
                ocs.extend(line.get("outcomes") or [])
            if not ocs:
                ocs = mkt.get("outcomes") or []
            rows.append(
                {
                    "name": name,
                    "ids": {"sub_type_id": str(mkt.get("sub_type_id", ""))},
                    "outcomes": [str(o.get("outcome_name") or o.get("outcome_key", "")) for o in ocs[:4]],
                    "extra": {"market_keys": list(mkt.keys())[:12]},
                }
            )
        return rows

    if book == Bookmaker.SPORTYBET:
        resp = await adapter._get(
            f"{adapter._api}/event",
            params={"productId": 3, "eventId": event.external_id},
        )
        for mkt in resp.json().get("data", {}).get("markets", []) or []:
            name = str(mkt.get("name") or mkt.get("marketName", ""))
            ocs = mkt.get("outcomes") or []
            rows.append(
                {
                    "name": name,
                    "ids": {
                        "market_id": str(mkt.get("id") or mkt.get("marketId") or ""),
                        "specifier": str(mkt.get("specifier") or ""),
                    },
                    "outcomes": [str(o.get("desc") or o.get("name", "")) for o in ocs[:4]],
                    "extra": {"market_keys": list(mkt.keys())[:12]},
                }
            )
        return rows

    if book == Bookmaker.BETPAWA:
        resp = await adapter._get(f"{adapter._api}/events/{event.external_id}")
        for mkt in resp.json().get("markets", []) or []:
            mt = mkt.get("marketType") or {}
            name = str(mt.get("displayName") or mt.get("name", ""))
            ocs = []
            for price_row in mkt.get("row") or []:
                for p in price_row.get("prices") or []:
                    ocs.append(str(p.get("displayName") or p.get("name", "")))
            rows.append(
                {
                    "name": name,
                    "ids": {
                        "market_type_id": str(mt.get("id", "")),
                        "market_type_name": str(mt.get("name", "")),
                    },
                    "outcomes": ocs[:4],
                    "extra": {"market_keys": list(mt.keys())[:12]},
                }
            )
        return rows

    if book == Bookmaker.SPORTPESA:
        url = f"{adapter._base}/api/games/markets?games={event.external_id}&markets=all"
        payload = (await adapter.curl.async_get(url)).json()
        for mkt in payload if isinstance(payload, list) else []:
            name = str(mkt.get("name") or mkt.get("marketName") or "")
            ocs = mkt.get("selections") or mkt.get("outcomes") or []
            rows.append(
                {
                    "name": name,
                    "ids": {"market_id": str(mkt.get("id") or mkt.get("marketId") or "")},
                    "outcomes": [str(o.get("name") or o.get("shortName", "")) for o in ocs[:4]],
                    "extra": {"market_keys": list(mkt.keys())[:12]},
                }
            )
        return rows

    if book == Bookmaker.MOZZARTBET:
        subgames = await adapter._subgames_for_sport(sport)
        resp = await adapter._post(
            f"{adapter._base}/getBettingOdds",
            json={"matchIds": [int(event.external_id)], "subgames": subgames[:20]},
        )
        payload = resp.json()
        if not isinstance(payload, list) or not payload:
            return rows
        block = payload[0] or {}
        kodds = block.get("kodds") or {}
        grouped_names: set[str] = set()
        for kodd in kodds.values():
            if not kodd or not isinstance(kodd, dict):
                continue
            sg = kodd.get("subGame") or {}
            if not isinstance(sg, dict):
                continue
            name = str(sg.get("gameName") or sg.get("subGameName") or "")
            if not name or name in grouped_names:
                continue
            grouped_names.add(name)
            rows.append(
                {
                    "name": name,
                    "ids": {
                        "subgame_id": str(sg.get("id") or sg.get("subGame") or ""),
                        "kodd_id": str(kodd.get("id") or ""),
                    },
                    "outcomes": [str(sg.get("subGameName") or "")],
                    "extra": {"subgame_keys": list(sg.keys())[:12]},
                }
            )
        return rows

    if book == Bookmaker.BANGBET:
        resp = await adapter._post(
            f"{adapter._base}/match/odds",
            json={"matchId": event.external_id, "producer": 3},
        )
        data = resp.json().get("data", {})
        for group in data.get("marketList", []) or []:
            for mkt in group.get("markets", []) or []:
                name = str(mkt.get("name") or group.get("name") or "")
                ocs = mkt.get("outcomes") or []
                rows.append(
                    {
                        "name": name,
                        "ids": {
                            "market_id": str(mkt.get("id") or ""),
                            "specifiers": str(mkt.get("specifiers") or ""),
                        },
                        "outcomes": [str(o.get("desc") or o.get("name", "")) for o in ocs[:4]],
                        "extra": {"market_keys": list(mkt.keys())[:12]},
                    }
                )
        return rows

    if book == Bookmaker.SHABIKI:
        row = (await adapter._load_coupon_rows(sport)).get(event.external_id)
        if not row:
            return rows
        for mkt in row.get("Markets") or []:
            name = str(mkt.get("Name") or mkt.get("MarketName") or "")
            ocs = mkt.get("Fields") or mkt.get("Outcomes") or []
            rows.append(
                {
                    "name": name,
                    "ids": {
                        "market_id": str(mkt.get("MarketId") or mkt.get("Id") or ""),
                    },
                    "outcomes": [str(o.get("FieldName") or o.get("Name", "")) for o in ocs[:4]],
                    "extra": {"market_keys": list(mkt.keys())[:12]},
                }
            )
        return rows

    if book == Bookmaker.PALMSBET:
        qs = adapter._qs
        url = f"{adapter._api}/Sportsbook/GetEventDetails?{qs}&eventId={event.external_id}"
        payload = (await adapter._get(url)).json()
        for mkt in payload.get("Markets") or payload.get("markets") or []:
            name = str(mkt.get("Name") or mkt.get("MarketName") or "")
            ocs = mkt.get("Selections") or mkt.get("Outcomes") or []
            rows.append(
                {
                    "name": name,
                    "ids": {"market_id": str(mkt.get("Id") or mkt.get("MarketTypeId") or "")},
                    "outcomes": [str(o.get("Name") or "") for o in ocs[:4]],
                    "extra": {"market_keys": list(mkt.keys())[:12]},
                }
            )
        return rows

    return rows


def _summarize(rows: list[RawMarketRow]) -> dict[str, Any]:
    by_book_sport: dict[str, list[dict]] = defaultdict(list)
    unmapped: list[dict] = []
    id_maps: dict[str, dict[str, dict[str, str]]] = defaultdict(lambda: defaultdict(dict))

    for row in rows:
        if row.raw_name.startswith("__ERROR__"):
            continue
        entry = {
            "raw_name": row.raw_name,
            "ids": row.ids,
            "canonical_key": row.canonical_key,
            "mapped": row.mapped,
            "sample_outcomes": row.sample_outcomes,
        }
        by_book_sport[f"{row.bookmaker}:{row.sport}"].append(entry)
        if row.canonical_key and row.ids:
            for id_key, id_val in row.ids.items():
                if id_val:
                    id_maps[row.bookmaker][id_key][id_val] = row.canonical_key
        if not row.mapped:
            unmapped.append(asdict(row))

    # Dedupe unmapped by book/sport/name
    seen: set[tuple] = set()
    unique_unmapped = []
    for u in unmapped:
        k = (u["bookmaker"], u["sport"], u["raw_name"])
        if k in seen:
            continue
        seen.add(k)
        unique_unmapped.append(u)

    return {
        "by_book_sport": dict(by_book_sport),
        "id_maps": {b: dict(v) for b, v in id_maps.items()},
        "unmapped_count": len(unique_unmapped),
        "unmapped": unique_unmapped[:500],
        "total_raw": len(rows),
        "mapped_raw": sum(1 for r in rows if r.mapped and not r.raw_name.startswith("__ERROR__")),
    }


async def main() -> None:
    all_rows: list[RawMarketRow] = []
    books = [b for b in Bookmaker if get_bookmaker_config(b.value).get("status") == "live"]

    for book in books:
        for sport in SPORTS:
            if not _supports_sport(book, sport):
                continue
            print(f"Probing {book.value}/{sport.value}...")
            rows = await _probe_adapter(book, sport)
            all_rows.extend(rows)
            mapped = sum(1 for r in rows if r.mapped)
            print(f"  raw={len(rows)} mapped={mapped}")

    all_rows = _unique_rows(all_rows)
    summary = _summarize(all_rows)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps({"summary": summary, "rows": [asdict(r) for r in all_rows]}, indent=2),
        encoding="utf-8",
    )
    print(f"\nWrote {OUTPUT}")
    print(f"Total raw markets: {summary['total_raw']} mapped: {summary['mapped_raw']}")
    print(f"Unmapped unique: {summary['unmapped_count']}")


if __name__ == "__main__":
    asyncio.run(main())
