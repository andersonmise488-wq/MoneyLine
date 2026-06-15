from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime, timezone

from moneyline.config.settings import get_settings
from moneyline.constants import EVENT_LOOKAHEAD_HOURS
from moneyline.sports import SUPPORTED_SPORTS
from moneyline.web.cache import ScanCache, ScanSnapshot
from moneyline.pipeline.book_health import BookHealthTracker
from moneyline.pipeline.handshake import build_ops_diagnostics
from moneyline.web.scanner import run_arb_scan

logger = logging.getLogger(__name__)

_scan_lock = threading.Lock()
_scanning = False


def _get_hub():
    from moneyline.api.ws_hub import get_scan_hub

    return get_scan_hub()


def _ws_publish(coro) -> None:
    try:
        asyncio.run(coro)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(coro)
        finally:
            loop.close()


def _dispatch_alerts(opportunities) -> int:
    settings = get_settings()
    if not settings.scan_auto_alerts_enabled:
        return 0
    from moneyline.alerts.telegram import send_arbitrage_alerts, telegram_configured

    if not telegram_configured():
        return 0

    async def _send() -> int:
        from moneyline.alerts.routing import filter_telegram_alerts

        to_send = filter_telegram_alerts(opportunities, deduplicate=True)
        if not to_send:
            return 0
        from moneyline.alerts.telegram import send_arbitrage_alerts

        return await send_arbitrage_alerts(to_send, deduplicate=False)

    try:
        return asyncio.run(_send())
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_send())
        finally:
            loop.close()


def run_scan_and_cache(
    *,
    min_margin_pct: float | None = None,
    max_events: int | None = None,
    max_markets: int | None = None,
    send_alerts: bool | None = None,
) -> ScanSnapshot:
    """Run arb scan, merge active arbs, persist, broadcast WS, and alert."""
    global _scanning
    settings = get_settings()
    min_margin = min_margin_pct if min_margin_pct is not None else settings.web_scan_min_margin_pct
    events = max_events if max_events is not None else settings.web_scan_max_events
    markets = max_markets if max_markets is not None else settings.web_scan_max_markets
    alert = send_alerts if send_alerts is not None else settings.scan_auto_alerts_enabled

    with _scan_lock:
        if _scanning:
            return ScanCache.load()
        _scanning = True

    ScanCache.mark_scanning(
        min_margin_pct=min_margin,
        max_events=events,
        max_markets=markets,
        clear_opportunities=False,
    )

    hub = _get_hub()
    _ws_publish(
        hub.broadcast_scan_start(
            min_margin_pct=min_margin,
            max_events=events,
            max_markets=markets,
        )
    )

    try:
        opportunities, scanned_at, diagnostics = run_arb_scan(
            min_margin_pct=min_margin,
            max_events=events,
            max_markets=markets,
            lookahead_hours=EVENT_LOOKAHEAD_HOURS,
        )
        ops = build_ops_diagnostics(
            events_collected=diagnostics.events_collected,
            lookahead_hours=EVENT_LOOKAHEAD_HOURS,
        )
        ScanCache.save(
            opportunities,
            scanned_at=scanned_at,
            scanning=False,
            error=None,
            min_margin_pct=min_margin,
            max_events=events,
            max_markets=markets,
            diagnostics={
                "events_collected": diagnostics.events_collected,
                "events_with_markets": diagnostics.events_with_markets,
                "markets_collected": diagnostics.markets_collected,
                "clusters_matched": diagnostics.clusters_matched,
                "sports_scanned": diagnostics.sports_scanned,
                "supported_sports": [s.value for s in SUPPORTED_SPORTS],
                "best_cross_book_margin_pct": diagnostics.best_cross_book_margin_pct,
                "best_cross_book_label": diagnostics.best_cross_book_label,
                "bookmaker_stats": diagnostics.bookmaker_stats,
                "weak_bookmakers": diagnostics.weak_bookmakers,
                "book_health": ops["book_health"],
                "books_paused": ops["books_paused"],
                "match_review_count": ops["match_review_count"],
                "architecture": ops["architecture"],
                "scraper": ops.get("scraper"),
                "arbs_found": len(opportunities),
                "arbs_raw": len(opportunities),
                "arbs_by_sport": diagnostics.arbs_by_sport,
            },
        )
        logger.info(
            "Background scan saved %s opportunities (full overwrite)",
            len(opportunities),
        )
        snapshot = ScanCache.load()
        _ws_publish(hub.broadcast_snapshot(snapshot))
        if alert:
            sent = _dispatch_alerts(opportunities)
            if sent:
                logger.info("Auto-sent %s Telegram alert message(s)", sent)
        return snapshot
    except Exception as exc:
        logger.exception("Background scan failed: %s", exc)
        _ws_publish(hub.broadcast_scan_error(str(exc)))
        existing = ScanCache.load()
        ScanCache.save(
            existing.opportunities,
            scanned_at=existing.scanned_at or datetime.now(timezone.utc),
            scanning=False,
            error=str(exc),
            min_margin_pct=min_margin,
            max_events=events,
            max_markets=markets,
        )
        snapshot = ScanCache.load()
        _ws_publish(hub.broadcast_snapshot(snapshot))
        return snapshot
    finally:
        with _scan_lock:
            _scanning = False


def _background_loop(stop_event: threading.Event) -> None:
    settings = get_settings()
    poll_seconds = max(15, settings.web_scan_poll_seconds)
    interval_minutes = max(1, settings.web_scan_interval_minutes)

    while not stop_event.is_set():
        if ScanCache.recover_stuck_scanning():
            logger.warning("Recovered stuck scanning flag — scheduling fresh scan")
        snapshot = ScanCache.load()
        if not snapshot.scanning and ScanCache.is_stale(snapshot.scanned_at, interval_minutes):
            run_scan_and_cache()
        stop_event.wait(poll_seconds)


class BackgroundScanService:
    """Background scanner owned by the API server — no separate scraper process."""

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        if ScanCache.recover_stuck_scanning(max_minutes=0):
            logger.warning("Cleared orphaned scanning flag on startup")
        BookHealthTracker().prune_expired_cooldowns()
        snapshot = ScanCache.load()
        settings = get_settings()
        needs_scan = snapshot.scanned_at is None or ScanCache.is_stale(
            snapshot.scanned_at,
            settings.web_scan_interval_minutes,
        )
        if needs_scan and not snapshot.scanning:
            threading.Thread(target=run_scan_and_cache, daemon=True).start()
        self._stop.clear()
        self._thread = threading.Thread(target=_background_loop, args=(self._stop,), daemon=True)
        self._thread.start()
        logger.info("Background arb scanner started")

    def force_scan(self) -> ScanSnapshot:
        settings = get_settings()
        return run_scan_and_cache(
            min_margin_pct=settings.web_scan_min_margin_pct,
            max_events=settings.web_scan_max_events,
            max_markets=settings.web_scan_max_markets,
        )


_service: BackgroundScanService | None = None
_service_lock = threading.Lock()


def get_background_scanner() -> BackgroundScanService:
    global _service
    with _service_lock:
        if _service is None:
            _service = BackgroundScanService()
        return _service
