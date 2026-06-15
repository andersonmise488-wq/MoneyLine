"""All configured sports participate in full-system scans."""

from moneyline.models.schemas import Sport
from moneyline.sports import SUPPORTED_SPORTS, supported_sports
from moneyline.web.scanner import SPORT_SCAN_CONCURRENCY, run_arb_scan


def test_supported_sports_match_config():
    sports = supported_sports()
    assert len(sports) == 8
    assert Sport.SOCCER in sports
    assert Sport.TENNIS in sports
    assert Sport.ICE_HOCKEY in sports
    assert SUPPORTED_SPORTS == sports


def test_scanner_defaults_to_all_supported_sports():
    assert SPORT_SCAN_CONCURRENCY == len(SUPPORTED_SPORTS)
    # run_arb_scan accepts sports=None and uses SUPPORTED_SPORTS internally
    import inspect

    sig = inspect.signature(run_arb_scan)
    assert sig.parameters["sports"].default is None
