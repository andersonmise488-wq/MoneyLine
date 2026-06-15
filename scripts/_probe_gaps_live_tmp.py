"""Temporary live probe - read only exploration."""
from __future__ import annotations

import asyncio
import time

import httpx

from moneyline.bookmakers.curl_client import CurlClient
from moneyline.bookmakers.registry import get_adapter
from moneyline.config_loader import get_bookmaker_config
from moneyline.models.schemas import Bookmaker, Sport

HOURS = 72
now_ms = int(time.time() * 1000)
cutoff_ms = now_ms + HOURS * 3600 * 1000


async def probe_bangbet_volleyball() -> None:
    cfg = get_bookmaker_config("bangbet")
    base = cfg["base_url"].rstrip("/")
    sid = cfg["sport_ids"]["volleyball"]
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(
            f"{base}/match/list",
            json={"pageNo": 1, "pageSize": 50, "sportId": sid},
            headers=cfg["headers"],
        )
        data = r.json().get("data", {})
        total = data.get("total", 0)
        rows = []
        for g in data.get("data", []):
            rows.extend(g.get("matchVoList", []))
        in_window = sum(
            1
            for m in rows
            if m.get("scheduledTime", 0)
            and m.get("scheduledTime") <= cutoff_ms
            and m.get("simTag", 0) != 1
            and m.get("virtualTag", 0) != 1
        )
        r2 = await c.post(
            f"{base}/match/list",
            json={"pageNo": 1, "pageSize": 200},
            headers=cfg["headers"],
        )
        all_rows = []
        for g in r2.json().get("data", {}).get("data", []):
            all_rows.extend(g.get("matchVoList", []))
        vb = [m for m in all_rows if m.get("sportId") == "sr:sport:23"]
        print(
            f"BANGBET volleyball sportId={sid}: total={total} page_rows={len(rows)} in72h={in_window}"
        )
        print(f"  unfiltered page vb matches={len(vb)}")


async def probe_betika_volleyball() -> None:
    cfg = get_bookmaker_config("betika")
    base = cfg["base_url"].rstrip("/")
    sid = cfg["sport_ids"]["volleyball"]
    headers = cfg["headers"]
    async with httpx.AsyncClient(timeout=30, headers=headers) as c:
        url1 = (
            f"{base}/v1/uo/matches?page=0&limit=50&sub_type_id=1&sport_id={sid}"
            f"&sort_id=1&period_id=-1&esports=false"
        )
        std = (await c.get(url1)).json().get("data", [])
        url2 = f"{base}/v1/uo/matches?sport_id={sid}&limit=50&page=1"
        r2 = await c.get(url2)
        relaxed = r2.json().get("data", [])
        meta = r2.json().get("meta", {})
        sports = (await c.get(f"{base}/v1/uo/sports")).json().get("data", [])
        vb = next((s for s in sports if str(s.get("sport_id")) == sid), None)
        print(
            f"BETIKA volleyball id={sid}: standard={len(std)} relaxed={len(relaxed)} "
            f"meta_total={meta.get('total')}"
        )
        if vb:
            print(
                f"  sports tree: {vb.get('sport_name')} match_count={vb.get('match_count')}"
            )


async def probe_odibets_volleyball() -> None:
    cfg = get_bookmaker_config("odibets")
    slug = cfg["sport_slugs"]["volleyball"]
    headers = {**cfg["headers"], "Authorization": "Bearer", "Origin": "https://odibets.com"}
    async with httpx.AsyncClient(timeout=30, headers=headers) as c:
        r1 = await c.get(
            f"https://api.odi.site/sportsbook/v1?sport_id={slug}&per_page=1000"
            f"&sportsbook=sportsbook&resource=sport"
        )
        comps = r1.json().get("data", {}).get("competitions", [])
        matches = 0
        for comp in comps[:10]:
            cid = comp["competition_id"]
            r = await c.get(
                f"https://api.odi.site/sportsbook/v1?sport_id={slug}&competition_id={cid}"
                f"&per_page=1000&sportsbook=sportsbook&resource=sport"
            )
            matches += len(r.json().get("data", {}).get("matches", []))
        r2 = await c.get(
            f"{cfg['base_url']}/v4/matches?src=2&sport_id={slug}&tab=&country_id=&day=0"
            f"&sort_by=&competition_id=&trials=0&per_page=100&page=1",
            headers=cfg["headers"],
        )
        day_rows = 0
        for comp in r2.json().get("data", {}).get("competitions", []):
            day_rows += len(comp.get("matches") or [])
        print(
            f"ODIBETS volleyball slug={slug}: comps={len(comps)} "
            f"comp_matches_sample={matches} v4_day0={day_rows}"
        )


async def probe_sportpesa_volleyball() -> None:
    cfg = get_bookmaker_config("sportpesa")
    base = cfg["base_url"].rstrip("/")
    sid = cfg["sport_ids"]["volleyball"]
    curl = CurlClient(impersonate="chrome120", headers=cfg["headers"])
    try:
        r = await curl.async_get(
            f"{base}/api/upcoming/games?sportId={sid}&section=upcoming&pag_count=50&pag_min=1"
        )
        rows = r.json() or []
        nav_resp = await curl.async_get(f"{base}/api/navigation")
        nav = nav_resp.json()
        nav_sport = next((s for s in nav if str(s.get("id")) == sid), None)
        print(
            f"SPORTPESA volleyball id={sid}: upcoming={len(rows)} "
            f"nav_has_matches={nav_sport.get('has_matches') if nav_sport else None}"
        )
        if nav_sport:
            leagues = sum(len(c.get("leagues", [])) for c in nav_sport.get("countries", []))
            print(f"  nav leagues={leagues}")
    finally:
        curl.close()


async def probe_sportybet_volleyball() -> None:
    cfg = get_bookmaker_config("sportybet")
    base = cfg["base_url"].rstrip("/")
    sid = cfg["sport_ids"]["volleyball"]
    headers = cfg["headers"]
    async with httpx.AsyncClient(timeout=30, headers=headers) as c:
        r1 = await c.get(
            f"{base}/factsCenter/configurableLiveOrPrematchEvents",
            params={"sportId": sid, "withTwoUpMarket": "true", "withOneUpMarket": "true"},
        )
        p1 = r1.json()
        ev1 = sum(len(b.get("events", [])) for b in p1.get("data", []) or [])
        r2 = await c.get(
            f"{base}/factsCenter/commonThumbnailEvents",
            params={"sportId": sid, "productId": 3, "pageSize": 100, "pageNum": 1},
        )
        p2 = r2.json()
        ev2 = sum(len(b.get("events", [])) for b in p2.get("data", []) or [])
        print(
            f"SPORTYBET volleyball {sid}: configurable={ev1} thumbnail={ev2} "
            f"bizCodes={p1.get('bizCode')},{p2.get('bizCode')}"
        )


async def probe_palmsbet_baseball() -> None:
    cfg = get_bookmaker_config("palmsbet")
    api = cfg["base_url"].rstrip("/")
    qs = cfg["query_string"]
    sid = cfg["sport_ids"]["baseball"]

    def collect(nodes: list, out: list) -> None:
        for n in nodes:
            if isinstance(n, dict):
                if n.get("Events"):
                    out.extend(n["Events"])
                if n.get("Items"):
                    collect(n["Items"], out)

    async with httpx.AsyncClient(timeout=30, headers=cfg["headers"]) as c:
        r = await c.get(
            f"{api}/Sportsbook/GetEvents?{qs}&sportids={sid}&champids=0&categoryids=0&count=500"
        )
        items = r.json().get("Result", {}).get("Items", [])
        ev: list = []
        collect(items, ev)
        print(f"PALMSBET baseball id={sid}: events={len(ev)}")


async def probe_mozzart() -> None:
    cfg = get_bookmaker_config("mozzartbet")
    base = cfg["base_url"].rstrip("/")
    headers = cfg["headers"]
    async with httpx.AsyncClient(timeout=30, headers=headers) as c:
        games = (await c.get(f"{base}/getAllGames")).json()
        for label, sid in [("cricket", "78"), ("volleyball", "6")]:
            groups = games.get(sid, [])
            subgames = groups[0].get("subgameIds", []) if groups else []
            r = await c.post(
                f"{base}/betOffer2",
                json={
                    "sportIds": [int(sid)],
                    "competitionIds": [],
                    "sort": "bytime",
                    "specials": None,
                    "subgames": [],
                    "size": 250,
                    "mostPlayed": False,
                    "type": "betting",
                    "numberOfGames": 0,
                    "activeCompleteOffer": False,
                    "lang": "en",
                    "date": None,
                    "offset": 0,
                },
            )
            payload = r.json()
            print(
                f"MOZZART {label} id={sid}: subgames={len(subgames)} "
                f"matches={len(payload.get('matches', []))} total={payload.get('total')}"
            )


async def probe_pepeta() -> None:
    cfg = get_bookmaker_config("pepeta")
    base = cfg["base_url"].rstrip("/")
    headers = cfg["headers"]
    async with httpx.AsyncClient(timeout=30, headers=headers) as c:
        sports = (await c.get(f"{base}/v1/uo/sports")).json().get("data", [])
        names = [
            (str(s.get("sport_id")), s.get("sport_name"), s.get("match_count"))
            for s in sports
        ]
        print(f"PEPETA sports tree ({len(names)} sports): {names}")
        for sport_key, sid in [("tennis", "28"), ("volleyball", "35"), ("cricket", "37")]:
            r2 = await c.get(f"{base}/v1/uo/matches?sport_id={sid}&limit=50&page=1")
            rows = r2.json().get("data", [])
            print(
                f"  {sport_key} id={sid}: relaxed={len(rows)} "
                f"total={r2.json().get('meta', {}).get('total')}"
            )


async def adapter_counts() -> None:
    pairs = [
        (Bookmaker.BANGBET, Sport.VOLLEYBALL),
        (Bookmaker.BETIKA, Sport.VOLLEYBALL),
        (Bookmaker.ODIBETS, Sport.VOLLEYBALL),
        (Bookmaker.SPORTPESA, Sport.VOLLEYBALL),
        (Bookmaker.SPORTYBET, Sport.VOLLEYBALL),
        (Bookmaker.PALMSBET, Sport.BASEBALL),
        (Bookmaker.MOZZARTBET, Sport.CRICKET),
        (Bookmaker.MOZZARTBET, Sport.VOLLEYBALL),
        (Bookmaker.PEPETA, Sport.TENNIS),
    ]
    for bm, sp in pairs:
        try:
            async with get_adapter(bm) as ad:
                ev = await ad.fetch_prematch_events(sp, limit=0, lookahead_hours=72)
                print(f"ADAPTER {bm.value}/{sp.value}: {len(ev)} events")
        except Exception as e:
            print(f"ADAPTER {bm.value}/{sp.value}: ERROR {e}")


async def main() -> None:
    print("=== RAW API PROBES ===")
    await probe_bangbet_volleyball()
    await probe_betika_volleyball()
    await probe_odibets_volleyball()
    await probe_sportpesa_volleyball()
    await probe_sportybet_volleyball()
    await probe_palmsbet_baseball()
    await probe_mozzart()
    await probe_pepeta()
    print("\n=== ADAPTER COUNTS ===")
    await adapter_counts()


if __name__ == "__main__":
    asyncio.run(main())
