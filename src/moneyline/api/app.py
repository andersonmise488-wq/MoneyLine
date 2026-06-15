"""HTTP + WebSocket API for MoneyLine prematch scans and M-Pesa."""

from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse

from moneyline.api.ws_hub import (
    get_scan_hub,
    snapshot_to_admin_payload,
    snapshot_to_public_payload,
)
from moneyline.api.middleware import (
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
    configure_cors,
)
from moneyline.subscriptions.service import SubscriptionService
from moneyline.timezone import format_eat
from moneyline.bot.telegram_bot import notify_payment_success
from moneyline.subscriptions.plans import plan_label
from moneyline.web.background import get_background_scanner
from moneyline.web.cache import ScanCache

logger = logging.getLogger(__name__)
_STATIC = Path(__file__).resolve().parent / "static"
_bot_thread: threading.Thread | None = None


def _start_telegram_bot() -> None:
    """Run subscription bot in background (manual STK + /subscribe flow)."""
    global _bot_thread
    from moneyline.config.settings import get_settings

    if not get_settings().telegram_bot_token.strip():
        return
    if _bot_thread and _bot_thread.is_alive():
        return

    def _run() -> None:
        import asyncio

        from moneyline.bot.telegram_bot import TelegramBot

        try:
            asyncio.run(TelegramBot().run_forever())
        except Exception as exc:
            logger.error("Telegram bot stopped: %s", exc)

    _bot_thread = threading.Thread(target=_run, name="telegram-bot", daemon=True)
    _bot_thread.start()
    logger.info("Telegram subscription bot started with API")


def _html(name: str) -> HTMLResponse:
    path = _STATIC / name
    return HTMLResponse(path.read_text(encoding="utf-8"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    from moneyline.pipeline.book_health import BookHealthTracker

    BookHealthTracker().prune_expired_cooldowns()
    get_background_scanner().start()
    _start_telegram_bot()
    logger.info("Prematch scanner + WebSocket feeds started with API")
    yield


app = FastAPI(title="MoneyLine API", version="0.4.0", lifespan=lifespan)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
configure_cors(app)
_service = SubscriptionService()


def _scan_command_allowed(message: str) -> bool:
    from moneyline.config.settings import get_settings

    settings = get_settings()
    token = settings.web_admin_token.strip()
    cmd = message.strip()
    if cmd in ("scan", "refresh"):
        return not token
    if token and cmd in (f"scan {token}", f"refresh {token}"):
        return True
    return False


def _admin_token_from_request(request: Request) -> str:
    header = request.headers.get("X-Admin-Token", "").strip()
    if header:
        return header
    return request.query_params.get("token", "").strip()


def _admin_access_allowed(request: Request) -> bool:
    from moneyline.config.settings import get_settings

    required = get_settings().web_admin_token.strip()
    if not required:
        return True
    return _admin_token_from_request(request) == required


def _require_admin(request: Request) -> None:
    if not _admin_access_allowed(request):
        raise HTTPException(status_code=401, detail="Admin token required")


@app.get("/health")
async def health() -> dict:
    from moneyline.config.settings import get_settings
    from moneyline.constants import EVENT_LOOKAHEAD_HOURS, MIN_HEALTHY_EVENTS
    from moneyline.pipeline.handshake import architecture_flags
    from moneyline.sports import SUPPORTED_SPORTS

    settings = get_settings()
    snapshot = ScanCache.load()
    diagnostics = snapshot.diagnostics or {}
    scraper = diagnostics.get("scraper")
    if scraper is None and diagnostics.get("events_collected") is not None:
        from moneyline.events.health import evaluate_scraper_health

        scraper = evaluate_scraper_health(
            int(diagnostics["events_collected"]),
            lookahead_hours=EVENT_LOOKAHEAD_HOURS,
        )
    return {
        "status": "ok" if not scraper or scraper.get("healthy", True) else "degraded",
        "mode": "prematch",
        "transport": "websocket",
        "supported_sports": [s.value for s in SUPPORTED_SPORTS],
        "architecture": architecture_flags(),
        "scraper": scraper
        or {
            "healthy": None,
            "min_events": MIN_HEALTHY_EVENTS,
            "lookahead_hours": EVENT_LOOKAHEAD_HOURS,
            "status": "unknown",
        },
        "automation": {
            "scanner": not snapshot.scanning or snapshot.scanned_at is not None,
            "telegram_bot": bool(settings.telegram_bot_token.strip()),
            "arb_alerts": settings.scan_auto_alerts_enabled,
            "alert_min_margin_pct": settings.alert_min_margin_pct,
            "match_first_markets": settings.match_first_markets,
            "market_fetch_concurrency": settings.market_fetch_concurrency,
            "raw_cache_ttl_seconds": settings.raw_cache_ttl_seconds,
            "subscriber_alerts": settings.subscriber_alerts_enabled,
            "billing": settings.billing_mode(),
        },
        "ops": {
            "match_review_count": (snapshot.diagnostics or {}).get("match_review_count"),
            "books_paused": (snapshot.diagnostics or {}).get("books_paused", []),
        },
    }


@app.get("/")
async def public_home() -> HTMLResponse:
    """Live public landing — WebSocket teaser feed, no backend stats."""
    return _html("public_dashboard.html")


@app.get("/admin")
async def admin_home() -> HTMLResponse:
    """Live admin console — full arb feed over WebSocket."""
    return _html("admin_dashboard.html")


@app.get("/live")
async def live_legacy() -> RedirectResponse:
    return RedirectResponse(url="/admin", status_code=302)


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard() -> HTMLResponse:
    return _html("subscribers_dashboard.html")


@app.get("/dashboard/stats")
async def dashboard_stats() -> dict:
    raw = _service.repo.subscription_stats()
    raw["generated_at"] = raw["generated_at"].isoformat()
    return raw


@app.get("/api/subscribers")
async def list_subscribers(request: Request, limit: int = 100) -> dict:
    _require_admin(request)
    stats = _service.repo.subscription_stats()
    stats["generated_at"] = stats["generated_at"].isoformat()
    subscribers = [
        SubscriptionService.subscriber_payload(sub)
        for sub in _service.list_subscribers(limit=min(limit, 500))
    ]
    payments = _service.repo.list_recent_payments(limit=25)
    return {
        "stats": stats,
        "subscribers": subscribers,
        "recent_payments": payments,
    }


@app.post("/api/subscribers/{telegram_chat_id}/terminate")
async def terminate_subscriber(telegram_chat_id: str, request: Request) -> dict:
    _require_admin(request)
    subscriber = await _service.terminate(telegram_chat_id)
    if subscriber is None:
        raise HTTPException(status_code=404, detail="Subscriber not found")
    return {
        "ok": True,
        "subscriber": SubscriptionService.subscriber_payload(subscriber),
    }


@app.post("/api/subscribers/{telegram_chat_id}/disconnect")
async def disconnect_subscriber(telegram_chat_id: str, request: Request) -> dict:
    return await terminate_subscriber(telegram_chat_id, request)


@app.get("/api/ops/book-health")
async def ops_book_health(request: Request) -> dict:
    _require_admin(request)
    from moneyline.pipeline.book_health import BookHealthTracker

    return {"books": BookHealthTracker().snapshot()}


@app.get("/api/ops/match-review")
async def ops_match_review(request: Request, limit: int = 50) -> dict:
    _require_admin(request)
    from moneyline.matching.review import MatchReviewQueue

    return {"items": MatchReviewQueue().list_items(limit=min(limit, 100))}


@app.post("/api/ops/match-review/{cluster_id}/dismiss")
async def ops_dismiss_match_review(cluster_id: str, request: Request) -> dict:
    _require_admin(request)
    from moneyline.matching.review import MatchReviewQueue

    ok = MatchReviewQueue().dismiss(cluster_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Review item not found")
    return {"ok": True}


@app.get("/static/{filename}")
async def static_asset(filename: str) -> FileResponse:
    path = _STATIC / filename
    if not path.is_file():
        from fastapi import HTTPException
        raise HTTPException(status_code=404)
    return FileResponse(path)


@app.get("/api/scan/latest")
async def scan_latest() -> dict:
    snapshot = ScanCache.load()
    return snapshot_to_admin_payload(snapshot)


@app.get("/api/public/latest")
async def public_latest() -> dict:
    snapshot = ScanCache.load()
    return snapshot_to_public_payload(snapshot)


@app.websocket("/ws/scan")
async def ws_scan_admin(websocket: WebSocket) -> None:
    """Full prematch feed for admin dashboards."""
    hub = get_scan_hub()
    await hub.connect_admin(websocket)
    try:
        snapshot = ScanCache.load()
        await websocket.send_json(snapshot_to_admin_payload(snapshot))
        while True:
            msg = await websocket.receive_text()
            cmd = msg.strip().lower()
            if cmd == "ping":
                await websocket.send_json({"type": "pong"})
            elif _scan_command_allowed(msg):
                get_background_scanner().force_scan()
            elif msg.strip().lower() in ("scan", "refresh"):
                await websocket.send_json({"type": "error", "error": "admin token required"})
    except WebSocketDisconnect:
        await hub.disconnect_admin(websocket)
    except Exception as exc:
        logger.warning("Admin WebSocket error: %s", exc)
        await hub.disconnect_admin(websocket)


@app.websocket("/ws/public")
async def ws_scan_public(websocket: WebSocket) -> None:
    """Marketing-safe live feed — teaser arbs only."""
    hub = get_scan_hub()
    await hub.connect_public(websocket)
    try:
        snapshot = ScanCache.load()
        await websocket.send_json(snapshot_to_public_payload(snapshot))
        while True:
            msg = await websocket.receive_text()
            if msg.strip().lower() == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        await hub.disconnect_public(websocket)
    except Exception as exc:
        logger.warning("Public WebSocket error: %s", exc)
        await hub.disconnect_public(websocket)


@app.post("/mpesa/callback")
async def mpesa_callback(request: Request) -> JSONResponse:
    payload = await request.json()
    logger.info("M-Pesa callback received")

    await _service.notify_expired_subscribers()
    subscriber = await _service.handle_stk_callback(payload)
    if subscriber:
        plan = plan_label(subscriber.plan) if subscriber.plan else "Subscription"
        expiry = format_eat(subscriber.expires_at) if subscriber.expires_at else "unknown"
        await notify_payment_success(
            subscriber.telegram_chat_id,
            (
                f"<b>Payment successful</b>\n"
                f"Plan: {plan}\n"
                f"Active until: {expiry}\n"
                "You will now receive MoneyLine arb alerts."
            ),
        )

    return JSONResponse({"ResultCode": 0, "ResultDesc": "Accepted"})
