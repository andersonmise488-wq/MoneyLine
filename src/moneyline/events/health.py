from __future__ import annotations

from moneyline.constants import EVENT_LOOKAHEAD_HOURS, MIN_HEALTHY_EVENTS


def evaluate_scraper_health(
    events_collected: int,
    *,
    min_events: int = MIN_HEALTHY_EVENTS,
    lookahead_hours: int = EVENT_LOOKAHEAD_HOURS,
) -> dict:
    """Report whether a scan cycle collected enough prematch events."""
    healthy = events_collected >= min_events
    return {
        "healthy": healthy,
        "events_collected": events_collected,
        "min_events": min_events,
        "lookahead_hours": lookahead_hours,
        "status": "ok" if healthy else "degraded",
    }
