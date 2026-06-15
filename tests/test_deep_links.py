"""Tests for per-bookmaker Place Bet deep links."""

from __future__ import annotations

from moneyline.links.deep_links import attach_place_bet_urls, build_place_bet_url
from moneyline.models.schemas import ArbitrageOpportunity, MarketPeriod, Sport


def test_betika_place_bet_url_includes_match_and_selection():
    url = build_place_bet_url(
        {
            "bookmaker": "betika",
            "parent_match_id": "61301267",
            "sub_type_id": "1",
            "external_outcome_id": "1",
        },
        sport=Sport.SOCCER.value,
    )
    assert url == (
        "https://www.betika.com/en-ke/m/bet/61301267?sub_type_id=1&outcome_id=1"
    )


def test_odibets_place_bet_url():
    url = build_place_bet_url(
        {
            "bookmaker": "odibets",
            "parent_match_id": "61301271",
            "sub_type_id": "1",
            "external_outcome_id": "2",
        },
        sport=Sport.SOCCER.value,
    )
    assert url == (
        "https://odibets.com/match-details/61301271?sub_type_id=1&outcome_id=2"
    )


def test_sportybet_place_bet_url_encodes_event_and_outcome():
    url = build_place_bet_url(
        {
            "bookmaker": "sportybet",
            "external_id": "sr:match:61301267",
            "external_outcome_id": "1",
        },
        sport=Sport.SOCCER.value,
    )
    assert url == (
        "https://www.sportybet.com/ke/m/sport/football/event/"
        "sr%3Amatch%3A61301267?outcomeId=1"
    )


def test_betpawa_place_bet_url_uses_event_path():
    url = build_place_bet_url(
        {
            "bookmaker": "betpawa",
            "external_id": "34887251",
            "external_outcome_id": "1461236475",
        },
        sport=Sport.SOCCER.value,
    )
    assert url == (
        "https://www.betpawa.co.ke/event/34887251?outcomeId=1461236475&priceId=1461236475"
    )


def test_attach_place_bet_urls_adds_links_to_all_legs():
    opp = ArbitrageOpportunity(
        cluster_id="c1",
        sport=Sport.SOCCER,
        market_key="match_result_1x2",
        market_display="1X2",
        period=MarketPeriod.FULL_TIME,
        line=None,
        home_team="A",
        away_team="B",
        competition="League",
        start_time="2026-05-23T12:00:00Z",
        margin_pct=5.0,
        implied_sum=0.95,
        legs=[
            {
                "bookmaker": "betika",
                "side": "home",
                "label": "A",
                "price": 2.1,
                "parent_match_id": "100",
                "sub_type_id": "1",
                "external_outcome_id": "1",
            },
            {
                "bookmaker": "odibets",
                "side": "away",
                "label": "B",
                "price": 2.2,
                "parent_match_id": "200",
                "sub_type_id": "1",
                "external_outcome_id": "2",
            },
        ],
    )
    enriched = attach_place_bet_urls(opp)
    assert enriched.legs[0]["place_bet_url"].endswith("outcome_id=1")
    assert enriched.legs[1]["place_bet_url"].startswith("https://odibets.com/match-details/200")
