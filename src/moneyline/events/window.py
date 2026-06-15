from __future__ import annotations

from datetime import datetime, timedelta, timezone

from moneyline.constants import EVENT_LOOKAHEAD_HOURS, EVENT_PAST_GRACE_MINUTES
from moneyline.models.schemas import Event
from moneyline.timezone import as_utc


def window_bounds(
    hours: int | None = None,
    *,
    past_grace_minutes: int = EVENT_PAST_GRACE_MINUTES,
) -> tuple[datetime, datetime]:
    """Return inclusive lower/upper UTC bounds for prematch collection."""
    now = datetime.now(timezone.utc)
    lookahead = hours if hours is not None else EVENT_LOOKAHEAD_HOURS
    lower = now - timedelta(minutes=past_grace_minutes)
    upper = now + timedelta(hours=lookahead)
    return lower, upper


def window_upper_bound(hours: int | None = None) -> datetime:
    return window_bounds(hours)[1]


def event_in_window(
    start_time: datetime,
    hours: int | None = None,
    *,
    past_grace_minutes: int = EVENT_PAST_GRACE_MINUTES,
) -> bool:
    lower, upper = window_bounds(hours, past_grace_minutes=past_grace_minutes)
    start = as_utc(start_time)
    return lower <= start <= upper


def filter_events_in_window(
    events: list[Event],
    hours: int | None = None,
) -> list[Event]:
    return [event for event in events if event_in_window(event.start_time, hours)]


def page_beyond_window(
    start_times: list[datetime],
    hours: int | None = None,
) -> bool:
    """True when every start time in a page is after the lookahead window."""
    if not start_times:
        return False
    _, upper = window_bounds(hours)
    return all(as_utc(start) > upper for start in start_times)


def page_starts_after_window(
    start_times: list[datetime],
    hours: int | None = None,
) -> bool:
    """True when the earliest kickoff on a sorted page is after the window."""
    if not start_times:
        return False
    _, upper = window_bounds(hours)
    earliest = min(as_utc(start) for start in start_times)
    return earliest > upper
