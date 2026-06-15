from datetime import datetime, timezone

from moneyline.events.prematch import filter_prematch_only, is_prematch_event, row_is_live
from moneyline.models.schemas import Bookmaker, Event, Sport


def test_is_prematch_rejects_live_flag():
    live = Event(
        event_key="x:1",
        bookmaker=Bookmaker.BETPAWA,
        external_id="1",
        sport=Sport.SOCCER,
        home_team="A",
        away_team="B",
        start_time=datetime.now(timezone.utc),
        is_live=True,
    )
    assert not is_prematch_event(live)


def test_is_prematch_rejects_live_raw_row():
    prematch = Event(
        event_key="x:2",
        bookmaker=Bookmaker.BANGBET,
        external_id="2",
        sport=Sport.SOCCER,
        home_team="A",
        away_team="B",
        start_time=datetime.now(timezone.utc),
        is_live=False,
        raw={"matchStatus": "live"},
    )
    assert not is_prematch_event(prematch)


def test_row_is_live_detects_common_book_fields():
    assert row_is_live({"matchStatus": "live"})
    assert row_is_live({"status": 1})
    assert row_is_live({"producer": 1})
    assert row_is_live({"productId": 1})
    assert not row_is_live({"matchStatus": "not_started", "producer": 3})


def test_filter_prematch_only():
    prematch = Event(
        event_key="x:2",
        bookmaker=Bookmaker.BETPAWA,
        external_id="2",
        sport=Sport.SOCCER,
        home_team="A",
        away_team="B",
        start_time=datetime.now(timezone.utc),
        is_live=False,
    )
    live = prematch.model_copy(update={"is_live": True, "event_key": "x:3", "external_id": "3"})
    assert filter_prematch_only([prematch, live]) == [prematch]
