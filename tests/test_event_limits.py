from __future__ import annotations

from moneyline.events.limits import (
    UNLIMITED_EVENTS,
    event_limit_reached,
    is_unlimited_event_limit,
    max_pages_for,
    page_size_for,
    trim_events,
)


def test_unlimited_limit() -> None:
    assert UNLIMITED_EVENTS == 0
    assert is_unlimited_event_limit(0)
    assert is_unlimited_event_limit(-1)
    assert not is_unlimited_event_limit(10)


def test_event_limit_reached() -> None:
    assert not event_limit_reached(5, 0)
    assert not event_limit_reached(99, 0)
    assert not event_limit_reached(9, 10)
    assert event_limit_reached(10, 10)


def test_trim_events() -> None:
    data = [1, 2, 3, 4, 5]
    assert trim_events(data, 0) == data
    assert trim_events(data, 2) == [1, 2]


def test_page_size_for() -> None:
    assert page_size_for(0, default=50, maximum=100) == 100
    assert page_size_for(10, default=50, maximum=100) == 50
    assert page_size_for(200, default=50, maximum=100) == 100


def test_max_pages_for() -> None:
    assert max_pages_for(0, capped=30, unlimited=200) == 200
    assert max_pages_for(25, capped=30, unlimited=200) == 30
