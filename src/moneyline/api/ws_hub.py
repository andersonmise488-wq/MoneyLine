from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket

from moneyline.alerts.telegram import participants_label, sport_heading
from moneyline.arb.identity import opportunity_id
from moneyline.models.schemas import ArbitrageOpportunity
from moneyline.web.cache import ScanSnapshot
from moneyline.config.settings import get_settings
from moneyline.alerts.routing import filter_premium_feed, filter_public_feed, filter_realistic_for_feed
from moneyline.web.filters import filter_premium_arbs

logger = logging.getLogger(__name__)


def _filter_fresh_opportunities(
    opportunities: list[ArbitrageOpportunity],
    *,
    now: datetime | None = None,
) -> list[ArbitrageOpportunity]:
    """Drop arbs whose odds TTL has expired."""
    now = now or datetime.now(timezone.utc)
    fresh: list[ArbitrageOpportunity] = []
    for opp in opportunities:
        if opp.expires_at is None:
            fresh.append(opp)
            continue
        expires = opp.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires > now:
            fresh.append(opp)
    return fresh


def _serialize_opportunity(opp: ArbitrageOpportunity) -> dict[str, Any]:
    payload = opp.model_dump(mode="json")
    payload["opportunity_id"] = opportunity_id(opp)
    return payload


def snapshot_to_payload(snapshot: ScanSnapshot) -> dict[str, Any]:
    return {
        "type": "scan_snapshot",
        "scanned_at": snapshot.scanned_at.isoformat() if snapshot.scanned_at else None,
        "scanning": snapshot.scanning,
        "error": snapshot.error,
        "min_margin_pct": snapshot.min_margin_pct,
        "max_events": snapshot.max_events,
        "max_markets": snapshot.max_markets,
        "total": snapshot.total,
        "diagnostics": snapshot.diagnostics,
        "opportunities": [_serialize_opportunity(o) for o in snapshot.opportunities],
    }


def _leg_payload(leg: dict, *, sport: str = "", market_key: str = "") -> dict[str, Any]:
    from moneyline.links.deep_links import build_place_bet_url

    payload: dict[str, Any] = {
        "bookmaker": str(leg.get("bookmaker", "")),
        "label": str(leg.get("label", leg.get("side", ""))),
        "side": str(leg.get("side", "")),
        "price": float(leg.get("price", 0)),
    }
    if leg.get("line") is not None:
        payload["line"] = float(leg["line"])
    if leg.get("stake") is not None:
        payload["stake"] = float(leg["stake"])
    if leg.get("return") is not None:
        payload["return"] = float(leg["return"])
    place_bet_url = leg.get("place_bet_url") or (
        build_place_bet_url(leg, sport=sport, market_key=market_key) if sport else None
    )
    if place_bet_url:
        payload["place_bet_url"] = place_bet_url
    return payload


def snapshot_to_public_payload(snapshot: ScanSnapshot) -> dict[str, Any]:
    """Free-band feed (≤3%) with legs for stake calculator."""
    settings = get_settings()
    live = _filter_fresh_opportunities(snapshot.opportunities)
    free = filter_public_feed(live, settings=settings)
    premium = filter_premium_feed(live, settings=settings)
    return {
        "type": "public_snapshot",
        "scanning": snapshot.scanning,
        "total": len(free),
        "premium_count": len(premium),
        "public_max_margin_pct": settings.web_public_max_margin_pct,
        "opportunities": [
            {
                "match": participants_label(opp),
                "margin_pct": round(opp.margin_pct, 2),
                "sport": sport_heading(opp.sport),
                "market": opp.market_display or opp.market_key,
                "market_key": opp.market_key,
                "line": opp.line,
                "home_team": opp.home_team,
                "away_team": opp.away_team,
                "legs": [
                    _leg_payload(
                        leg,
                        sport=opp.sport.value,
                        market_key=opp.market_key,
                    )
                    for leg in opp.legs
                ],
            }
            for opp in free[:50]
        ],
    }


def snapshot_to_admin_payload(snapshot: ScanSnapshot) -> dict[str, Any]:
    """Full feed — all arbs, no upper margin cap."""
    settings = get_settings()
    live = _filter_fresh_opportunities(snapshot.opportunities)
    active = filter_realistic_for_feed(live, settings=settings)
    premium = filter_premium_feed(active, settings=settings)
    free = filter_public_feed(active, settings=settings)
    payload = snapshot_to_payload(snapshot)
    payload["opportunities"] = [_serialize_opportunity(o) for o in active]
    payload["total"] = len(active)
    payload["premium_count"] = len(premium)
    payload["free_count"] = len(free)
    payload["stale_filtered"] = len(snapshot.opportunities) - len(live)
    return payload


class ScanWebSocketHub:
    """Broadcast prematch scan updates to connected dashboard/API clients."""

    def __init__(self) -> None:
        self._admin_clients: set[WebSocket] = set()
        self._public_clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect_admin(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._admin_clients.add(websocket)
        logger.info("Admin WS connected (%s total)", len(self._admin_clients))

    async def connect_public(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._public_clients.add(websocket)
        logger.info("Public WS connected (%s total)", len(self._public_clients))

    async def disconnect_admin(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._admin_clients.discard(websocket)

    async def disconnect_public(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._public_clients.discard(websocket)

    async def _broadcast_to(self, clients: set[WebSocket], message: dict[str, Any]) -> None:
        if not clients:
            return
        text = json.dumps(message, default=str)
        async with self._lock:
            targets = list(clients)
        dead: list[WebSocket] = []
        for ws in targets:
            try:
                await ws.send_text(text)
            except Exception:
                dead.append(ws)
        for ws in dead:
            async with self._lock:
                clients.discard(ws)

    async def broadcast_admin(self, message: dict[str, Any]) -> None:
        await self._broadcast_to(self._admin_clients, message)

    async def broadcast_public(self, message: dict[str, Any]) -> None:
        await self._broadcast_to(self._public_clients, message)

    async def broadcast_snapshot(self, snapshot: ScanSnapshot) -> None:
        await self.broadcast_admin(snapshot_to_admin_payload(snapshot))
        await self.broadcast_public(snapshot_to_public_payload(snapshot))

    async def broadcast_scan_start(
        self,
        *,
        min_margin_pct: float,
        max_events: int,
        max_markets: int,
    ) -> None:
        at = datetime.now(timezone.utc).isoformat()
        await self.broadcast_admin(
            {
                "type": "scan_start",
                "at": at,
                "min_margin_pct": min_margin_pct,
                "max_events": max_events,
                "max_markets": max_markets,
                "mode": "prematch",
            }
        )
        await self.broadcast_public({"type": "scan_start", "scanning": True})

    async def broadcast_scan_error(self, error: str) -> None:
        await self.broadcast_admin({"type": "scan_error", "error": error})
        await self.broadcast_public({"type": "scan_error"})


_hub: ScanWebSocketHub | None = None


def get_scan_hub() -> ScanWebSocketHub:
    global _hub
    if _hub is None:
        _hub = ScanWebSocketHub()
    return _hub
