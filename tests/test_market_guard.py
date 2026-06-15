"""Tests for strict market guard."""
from moneyline.markets.guard import accept_market_name, is_combo_market, should_drop_raw_market
from moneyline.markets.registry import MarketRegistry
from moneyline.models.schemas import Sport


def test_interval_1x2_rejected():
    assert should_drop_raw_market("10 minutes - 1x2 from 1 to 10")
    assert not accept_market_name("match_result_1x2", "10 minutes - 1x2 from 1 to 10", Sport.SOCCER)


def test_combo_btts_rejected():
    assert is_combo_market("1x2 & both teams to score")
    assert is_combo_market("Both teams to score 4+ corners")
    assert is_combo_market("Draw or both teams to score")
    assert should_drop_raw_market("1x2 & both teams to score")
    assert MarketRegistry().resolve(Sport.SOCCER, "1x2 & both teams to score") is None


def test_combo_outcome_and_total_rejected():
    assert is_combo_market("Outcome And Total Goals 1.5")
    assert is_combo_market("1st half - 1x2 & both teams to score")
    assert is_combo_market("Final Result + Total Goals Over/Under")
    assert is_combo_market("Half Time - Full Time")
    assert is_combo_market("Mozzart Combinations")
    assert MarketRegistry().resolve(Sport.SOCCER, "Outcome And Total Goals 1.5") is None


def test_standard_btts_accepted():
    assert accept_market_name("btts", "Both teams to score", Sport.SOCCER)
    assert accept_market_name("btts", "1st half - both teams to score", Sport.SOCCER)
    assert accept_market_name("btts", "BOTH TEAMS TO SCORE (GG/NG)", Sport.SOCCER)
    assert accept_market_name("btts", "GG/NG", Sport.SOCCER)


def test_draw_no_bet_money_back():
    assert accept_market_name(
        "draw_no_bet",
        "WHO WILL WIN? (IF DRAW, MONEY BACK)",
        Sport.SOCCER,
    )


def test_basketball_team_totals_half_o_u():
    assert accept_market_name("team_totals", "1st Half - Home O/U", Sport.BASKETBALL)
    assert accept_market_name("team_totals", "xth quarter - competitor1 total", Sport.BASKETBALL)


def test_soccer_half_totals():
    assert accept_market_name("half_totals", "1ST HALF - TOTAL", Sport.SOCCER)
    assert accept_market_name("half_totals", "2nd Half - Total", Sport.SOCCER)


def test_corners_over_under_alias():
    assert accept_market_name("corners_totals", "Corners - Over/Under", Sport.SOCCER)


def test_baseball_first_5_innings_totals():
    assert accept_market_name(
        "first_5_innings_totals",
        "Innings 1 to 5 - total",
        Sport.BASEBALL,
    )


def test_team_total_requires_team_signal():
    assert not accept_market_name("team_totals", "Total Goals (2.5)", Sport.SOCCER)
    assert accept_market_name("team_totals", "Total Goals Over/Under Home Team", Sport.SOCCER)


def test_match_total_rejects_team():
    assert not accept_market_name("over_under_goals", "Home team total goals 1.5", Sport.SOCCER)
    assert accept_market_name("over_under_goals", "Total Goals Over/Under", Sport.SOCCER)


def test_draw_no_bet_strict():
    assert accept_market_name("draw_no_bet", "Draw No Bet", Sport.SOCCER)
    assert not accept_market_name("draw_no_bet", "Draw No Bet & Total", Sport.SOCCER)


def test_moneyline_rejects_1x2():
    assert not accept_market_name("moneyline", "1x2", Sport.BASKETBALL)
    assert accept_market_name("moneyline", "Moneyline", Sport.BASKETBALL)


def test_corners_totals_rejects_team_markets():
    assert accept_market_name("corners_totals", "Total corners", Sport.SOCCER)
    assert accept_market_name("corners_totals", "1st half - total corners", Sport.SOCCER)
    assert not accept_market_name("corners_totals", "1 total corners", Sport.SOCCER)
    assert not accept_market_name("corners_totals", "2 total corners", Sport.SOCCER)
    assert not accept_market_name("corners_totals", "1st half - 1 total corners", Sport.SOCCER)
    assert not accept_market_name("corners_totals", "Home Team Total Corners", Sport.SOCCER)
    assert not accept_market_name("corners_totals", "SSC Napoli total corners", Sport.SOCCER)
    reg = MarketRegistry()
    assert reg.resolve(Sport.SOCCER, "1 total corners") is None
    assert reg.resolve(Sport.SOCCER, "Total corners") is not None
