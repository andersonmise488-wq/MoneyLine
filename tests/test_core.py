from moneyline.arb.engine import arb_margin, implied_probability
from moneyline.matching.fuzzy import normalize_team


def test_implied_probability():
    assert abs(implied_probability(2.0) - 0.5) < 1e-9


def test_arb_margin_two_way():
    # 2.10 + 2.10 → implied sum < 1 → positive margin
    implied_sum, margin = arb_margin([2.10, 2.10])
    assert implied_sum < 1.0
    assert margin > 0


def test_normalize_team():
    assert "manchester" in normalize_team("Manchester United FC")
