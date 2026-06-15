"""Verify user-provided bookmaker API endpoints."""

from __future__ import annotations

import asyncio
import json
import urllib.parse

import httpx

RESULTS: list[dict] = []


def record(name: str, url: str, status: int | None, ok: bool, detail: str) -> None:
    RESULTS.append({"bookmaker": name, "url": url[:120], "status": status, "ok": ok, "detail": detail[:200]})
    mark = "OK" if ok else "FAIL"
    print(f"[{mark}] {name}: {status} — {detail[:100]}")


async def main() -> None:
    async with httpx.AsyncClient(follow_redirects=True, timeout=25.0) as c:
        # BangBet
        r = await c.post(
            "https://bet-api.bangbet.com/api/bet/match/list",
            json={"pageNo": 1, "pageSize": 5, "sportId": "sr:sport:1"},
            headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
        )
        ok = r.status_code == 200 and r.text[:1] in "{["
        record("bangbet", "/match/list", r.status_code, ok, r.text[:150])

        # BetPawa
        q = json.dumps(
            {
                "queries": [
                    {
                        "query": {"eventType": "UPCOMING", "categories": ["2"]},
                        "view": {"marketTypes": ["1X2"]},
                        "sort": {"startTime": "ASC"},
                        "take": 5,
                        "skip": 0,
                    }
                ]
            }
        )
        r = await c.get(
            f"https://www.betpawa.co.ke/api/sportsbook/v3/events/lists/by-queries?q={urllib.parse.quote(q)}",
            headers={
                "Accept": "application/json",
                "X-Pawa-Brand": "betpawa-kenya",
                "Origin": "https://www.betpawa.co.ke",
                "Referer": "https://www.betpawa.co.ke/",
            },
        )
        ok = r.status_code == 200 and "error" not in r.text.lower()[:200]
        record("betpawa", "/v3/events/lists/by-queries", r.status_code, ok, r.text[:150])

        # Mozzartbet
        r = await c.get(
            "https://www.mozzartbet.co.ke/getAllGames",
            headers={"X-Requested-With": "XMLHttpRequest", "User-Agent": "Mozilla/5.0"},
        )
        ok = r.status_code == 200 and r.text[:1] == "["
        record("mozzartbet", "/getAllGames", r.status_code, ok, r.text[:150])

        r = await c.post(
            "https://www.mozzartbet.co.ke/betOffer2",
            json={
                "sportIds": [1],
                "competitionIds": [],
                "sort": "bycompetition",
                "specials": None,
                "subgames": [],
                "size": 5,
                "mostPlayed": False,
                "type": "betting",
                "numberOfGames": 0,
                "activeCompleteOffer": False,
                "lang": "en",
                "date": None,
                "offset": 0,
            },
            headers={"X-Requested-With": "XMLHttpRequest", "Content-Type": "application/json"},
        )
        ok = r.status_code == 200 and "items" in r.text or "matches" in r.text.lower()
        record("mozzartbet", "/betOffer2", r.status_code, ok, r.text[:150])

        # Odibets odi.site
        r = await c.get(
            "https://api.odi.site/sportsbook/v1?sport_id=soccer&per_page=10&sportsbook=sportsbook&resource=sport",
            headers={"Referer": "https://odibets.com/"},
        )
        ok = r.status_code == 200 and r.text[:1] in "{["
        record("odibets_odi", "/sportsbook/v1 sport", r.status_code, ok, r.text[:150])

        # Palmsbet
        r = await c.get(
            "https://sb2frontend-altenar2.biahosted.com/api/Sportsbook/GetEvents"
            "?timezoneOffset=-180&langId=8&skinName=palmsbet&integration=palmsbet.co.ke"
            "&sportids=66&champids=0&categoryids=0&count=5"
        )
        ok = r.status_code == 200 and "Events" in r.text or "events" in r.text
        record("palmsbet", "/GetEvents", r.status_code, ok, r.text[:150])

        # Pepeta
        r = await c.get(
            "https://api.pepeta.com/v1/uo/matches?sport_id=14&limit=5&page=0&sub_type_id=1&sort_id=1",
            headers={"Origin": "https://www.pepeta.com", "Accept": "application/json"},
        )
        ok = r.status_code == 200 and '"data"' in r.text
        record("pepeta", "/uo/matches", r.status_code, ok, r.text[:150])

        # Shabiki
        r = await c.get(
            "https://sports-apipro.logiqsport.com/api/Pregame/Coupon"
            "?lang=en&siteid=28&providerid=1&type=upcoming&sportId=1&pagination=true&sliceStart=0&sliceEnd=5"
        )
        ok = r.status_code == 200 and r.text[:1] in "{["
        record("shabiki", "/Pregame/Coupon", r.status_code, ok, r.text[:150])

        # SportPesa
        r = await c.get(
            "https://www.ke.sportpesa.com/api/upcoming/games?sportId=1&section=upcoming&pag_count=5&pag_min=1",
            headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"},
        )
        ok = r.status_code in (200, 206) and r.text[:1] == "["
        record("sportpesa", "/upcoming/games", r.status_code, ok, r.text[:150])

        # SportyBet
        r = await c.get(
            "https://www.sportybet.com/api/ke/factsCenter/configurableLiveOrPrematchEvents"
            "?sportId=sr:sport:1&withTwoUpMarket=true&withOneUpMarket=true",
            headers={"Referer": "https://www.sportybet.com/ke/", "Accept": "application/json"},
        )
        ok = r.status_code == 200 and r.text[:1] == "{"
        record("sportybet", "/configurableLiveOrPrematchEvents", r.status_code, ok, r.text[:150])

        # Betika (verify)
        r = await c.get(
            "https://api.betika.com/v1/uo/matches?limit=5&page=0&sport_id=14&sub_type_id=1",
            headers={"Origin": "https://www.betika.com"},
        )
        ok = r.status_code == 200 and '"data"' in r.text
        record("betika", "/uo/matches", r.status_code, ok, r.text[:150])

    working = [x for x in RESULTS if x["ok"]]
    print(f"\n=== {len(working)}/{len(RESULTS)} working ===")
    for w in working:
        print(f"  + {w['bookmaker']}")


if __name__ == "__main__":
    asyncio.run(main())
