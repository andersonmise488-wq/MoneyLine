from moneyline.constants import EVENT_LOOKAHEAD_HOURS, MIN_HEALTHY_EVENTS
from moneyline.events.health import evaluate_scraper_health


def test_evaluate_scraper_health_ok() -> None:
    result = evaluate_scraper_health(1500)
    assert result["healthy"] is True
    assert result["status"] == "ok"
    assert result["min_events"] == MIN_HEALTHY_EVENTS
    assert result["lookahead_hours"] == EVENT_LOOKAHEAD_HOURS


def test_evaluate_scraper_health_degraded() -> None:
    result = evaluate_scraper_health(400)
    assert result["healthy"] is False
    assert result["status"] == "degraded"
