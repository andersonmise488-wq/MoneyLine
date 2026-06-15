from __future__ import annotations

import re

from moneyline.models.schemas import Event

_LIVE_STATUS_TOKENS = frozenset(
    {
        "live",
        "inplay",
        "in_play",
        "in progress",
        "inprogress",
        "playing",
        "running",
    }
)
_LIVE_MATCH_STATUS = frozenset(_LIVE_STATUS_TOKENS | {"1", "started"})
_PREMATCH_STATUS = frozenset(
    {
        "not_started",
        "not started",
        "notstarted",
        "prematch",
        "pre-match",
        "scheduled",
        "upcoming",
    }
)
_LIVE_PRODUCER_ID = 1
_PREMATCH_PRODUCER_ID = 3


def _token_is_live(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value == 1
    text = str(value).strip().lower()
    if not text or text in _PREMATCH_STATUS:
        return False
    if text in _LIVE_MATCH_STATUS:
        return True
    parts = [p for p in re.split(r"[\s_\-/]+", text) if p]
    if "not" in parts and "started" in parts:
        return False
    if set(parts) & _LIVE_STATUS_TOKENS:
        return True
    return "in play" in text or "in progress" in text


def row_is_live(raw: dict | None) -> bool:
    """True when a bookmaker API row represents an in-play fixture."""
    if not raw:
        return False
    if raw.get("isLive") or raw.get("IsLiveEvent") or raw.get("is_live"):
        return True
    if _token_is_live(raw.get("matchStatus")):
        return True
    if _token_is_live(raw.get("match_status")):
        return True
    if _token_is_live(raw.get("status")):
        return True
    state = raw.get("state")
    if isinstance(state, dict):
        if _token_is_live(state.get("name")) or _token_is_live(state.get("code")):
            return True
    elif _token_is_live(state):
        return True
    info = raw.get("additionalInfo") or {}
    if isinstance(info, dict) and info.get("live"):
        return True
    producer = raw.get("producer")
    if producer is not None and int(producer) == _LIVE_PRODUCER_ID:
        return True
    product_id = raw.get("productId")
    if product_id is not None and int(product_id) == _LIVE_PRODUCER_ID:
        return True
    return False


def is_prematch_event(event: Event) -> bool:
    """True when the event should be included in prematch-only scans."""
    if event.is_live:
        return False
    return not row_is_live(event.raw)


def filter_prematch_only(events: list[Event]) -> list[Event]:
    return [event for event in events if is_prematch_event(event)]


def prematch_producer_id(raw: dict | None = None) -> int:
    """Sportradar/BangBet producer id for prematch odds (never live producer 1)."""
    if raw:
        producer = raw.get("producer")
        if producer is not None and int(producer) == _PREMATCH_PRODUCER_ID:
            return _PREMATCH_PRODUCER_ID
    return _PREMATCH_PRODUCER_ID
