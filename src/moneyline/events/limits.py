from __future__ import annotations

"""Helpers for optional event-count caps during prematch collection."""

# Zero or negative limit = fetch every event inside the lookahead window.
UNLIMITED_EVENTS = 0


def is_unlimited_event_limit(limit: int) -> bool:
    return limit <= 0


def event_limit_reached(count: int, limit: int) -> bool:
    return limit > 0 and count >= limit


def trim_events(events: list, limit: int) -> list:
    return events[:limit] if limit > 0 else events


def page_size_for(limit: int, *, default: int = 100, maximum: int = 200) -> int:
    if is_unlimited_event_limit(limit):
        return maximum
    return min(max(limit, default), maximum)


def max_pages_for(limit: int, *, capped: int = 30, unlimited: int = 200) -> int:
    return unlimited if is_unlimited_event_limit(limit) else capped
