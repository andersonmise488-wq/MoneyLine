from datetime import datetime, timezone
import asyncio
from unittest.mock import AsyncMock, patch

from moneyline.alerts.formatting import format_bet_pick

from moneyline.alerts.telegram import (
    format_arb_html,
    format_arb_message,
    format_batch_summary_html,
    group_by_margin_bucket,
    margin_bucket_label,
    send_arbitrage_alerts,
    sport_emoji,
)

from moneyline.constants import ALERT_INDIVIDUAL_LIMIT

from moneyline.models.schemas import ArbitrageOpportunity, MarketPeriod, Sport





def _sample_opportunity(

    *,

    sport: Sport = Sport.SOCCER,

    margin_pct: float = 4.2,

    competition: str = "Premier League",

) -> ArbitrageOpportunity:

    return ArbitrageOpportunity(

        cluster_id="c1",

        sport=sport,

        market_key="over_under_goals",

        market_display="Over/Under Goals | Full Time | Over/Under 2.5",

        period=MarketPeriod.FULL_TIME,

        line=2.5,

        home_team="Arsenal",

        away_team="Chelsea",

        competition=competition,

        start_time=datetime(2026, 5, 23, 12, 0, tzinfo=timezone.utc),

        margin_pct=margin_pct,

        implied_sum=0.958,

        legs=[

            {

                "bookmaker": "betika",

                "side": "over",

                "label": "Over 2.5",

                "price": 2.10,

                "line": 2.5,

                "stake": 4761.90,

                "return": 10000.0,

            },

            {

                "bookmaker": "odibets",

                "side": "under",

                "label": "Under 2.5",

                "price": 1.95,

                "line": 2.5,

                "stake": 5238.10,

                "return": 10214.29,

            },

        ],

    )





def _handicap_opportunity() -> ArbitrageOpportunity:

    return ArbitrageOpportunity(

        cluster_id="c2",

        sport=Sport.SOCCER,

        market_key="asian_handicap",

        market_display="Asian Handicap | Full Time | Line -2",

        period=MarketPeriod.FULL_TIME,

        line=-2.0,

        home_team="Arsenal",

        away_team="Chelsea",

        competition="Premier League",

        start_time=datetime(2026, 5, 23, 12, 0, tzinfo=timezone.utc),

        margin_pct=3.5,

        implied_sum=0.965,

        legs=[

            {

                "bookmaker": "betika",

                "side": "home",

                "label": "Arsenal -2",

                "price": 6.00,

                "line": -2.0,

                "stake": 1666.67,

                "return": 10000.0,

            },

            {

                "bookmaker": "odibets",

                "side": "away",

                "label": "Chelsea +2",

                "price": 1.90,

                "line": -2.0,

                "stake": 5263.16,

                "return": 10000.0,

            },

        ],

    )





def test_sport_emoji():

    assert sport_emoji(Sport.SOCCER) == "⚽"

    assert sport_emoji(Sport.TENNIS) == "🎾"





def test_margin_bucket_label():

    assert margin_bucket_label(4.0) == "3.0-5.0%"

    assert margin_bucket_label(6.0) == "5.1-7.0%"

    assert margin_bucket_label(25.0) == "20.1%+"





def test_format_bet_pick_handicap():

    opp = _handicap_opportunity()

    assert format_bet_pick(opp, opp.legs[0]) == "Arsenal (-2) @ 6.00"

    assert format_bet_pick(opp, opp.legs[1]) == "Chelsea (+2) @ 1.90"





def test_format_arb_message_contains_required_fields():

    text = format_arb_message(_sample_opportunity())



    assert "🔥 ARB ALERT" in text

    assert "⚽ Soccer" in text

    assert "Event:        Premier League" in text

    assert "Participants: Arsenal vs Chelsea" in text

    assert "Kickoff:" in text

    assert "15:00 EAT" in text

    assert "Market:       Over/Under Goals" in text

    assert "Period:       Full Time" in text

    assert "Line:         2.5" in text

    assert "Margin:       4.20%" in text

    assert "Over 2.5 @ 2.10" in text

    assert "Under 2.5 @ 1.95" in text

    assert "Stake KES 4,761.90 · Return KES 10,000.00" in text

    assert "Leg 1" not in text

    assert "Leg 2" not in text

    assert "Pick:" not in text





def test_format_arb_html_includes_place_bet_links():
    opp = _sample_opportunity()
    opp = opp.model_copy(
        update={
            "legs": [
                {
                    **opp.legs[0],
                    "place_bet_url": "https://www.betika.com/en-ke/m/bet/100?sub_type_id=1&outcome_id=1",
                },
                {
                    **opp.legs[1],
                    "place_bet_url": "https://odibets.com/match-details/200?sub_type_id=1&outcome_id=2",
                },
            ]
        }
    )
    html = format_arb_html(opp)
    assert "Place Bet" in html
    assert "https://www.betika.com/en-ke/m/bet/100" in html
    assert "https://odibets.com/match-details/200" in html


def test_format_arb_html_escapes_teams_and_uses_new_layout():

    opp = _sample_opportunity(sport=Sport.BASKETBALL)

    opp.home_team = "A & B <script>"

    html = format_arb_html(opp)



    assert "<b>🔥 ARB ALERT</b>" in html

    assert "<b>🏀 Basketball</b>" in html

    assert "A &amp; B &lt;script&gt;" in html

    assert "<b>Event:</b> Premier League" in html

    assert "<b>Participants:</b>" in html

    assert "<b>Kickoff:</b>" in html

    assert "Over 2.5 @ 2.10" in html

    assert "<b>Margin:</b> 4.20%" in html

    assert "Leg 1" not in html





def test_format_arb_html_handicap_picks():

    html = format_arb_html(_handicap_opportunity())

    assert "Arsenal (-2) @ 6.00" in html

    assert "Chelsea (+2) @ 1.90" in html





def test_group_by_margin_bucket():

    opps = [

        _sample_opportunity(margin_pct=4.0),

        _sample_opportunity(margin_pct=6.5),

        _sample_opportunity(margin_pct=4.8),

    ]

    grouped = group_by_margin_bucket(opps)

    assert len(grouped["3.0-5.0%"]) == 2

    assert len(grouped["5.1-7.0%"]) == 1





def test_format_batch_summary_html():

    html = format_batch_summary_html(

        "3.0-5.0%",

        [_sample_opportunity(margin_pct=4.0)],

    )

    assert "🔥 ARB ALERT · Batch · Margin 3.0-5.0%" in html

    assert "⚽ Soccer" in html

    assert "Premier League" in html

    assert "Arsenal vs Chelsea" in html

    assert "Over 2.5 @ 2.10" in html

    assert "Margin 4.00%" in html

    assert "Leg 1" not in html





def test_individual_alert_limit_constant():

    assert ALERT_INDIVIDUAL_LIMIT == 100


def test_send_arbitrage_alerts_only_above_five_percent():
    low = _sample_opportunity(margin_pct=5.0)
    high = _sample_opportunity(margin_pct=5.1)

    with patch(
        "moneyline.alerts.telegram.send_arbitrage_alert", new_callable=AsyncMock
    ) as mock_send:
        mock_send.return_value = 1
        with patch(
            "moneyline.alerts.telegram.resolve_alert_targets", return_value=["123"]
        ):
            sent = asyncio.run(send_arbitrage_alerts([low, high], deduplicate=False))

    assert sent == 1
    assert mock_send.call_count == 1
    assert mock_send.call_args[0][0].margin_pct == 5.1

