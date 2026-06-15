from __future__ import annotations

from datetime import datetime, timedelta, timezone

from moneyline.events.window import page_beyond_window, page_starts_after_window, window_bounds


def test_page_starts_after_window() -> None:
    _, upper = window_bounds(72)
    in_window = upper - timedelta(hours=1)
    after_window = upper + timedelta(hours=1)

    assert not page_starts_after_window([in_window, after_window], 72)
    assert page_starts_after_window([after_window, after_window + timedelta(hours=1)], 72)
    assert page_beyond_window([after_window, after_window + timedelta(hours=1)], 72)
