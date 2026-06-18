"""Telegram /subscribe command parsing."""

from moneyline.bot.telegram_bot import (
    is_bare_subscribe_command,
    parse_subscribe_plan,
    PLAN_CHOICE_PATTERN,
    SUBSCRIBE_PLAN_PATTERN,
)
from moneyline.subscriptions.models import SubscriptionPlan


def test_subscribe_weekly_command() -> None:
    plan = parse_subscribe_plan("/subscribe weekly")
    assert plan == SubscriptionPlan.WEEKLY


def test_subscribe_weekly_with_bot_username() -> None:
    plan = parse_subscribe_plan("/subscribe@MoneyLine_bot weekly")
    assert plan == SubscriptionPlan.WEEKLY


def test_subscribe_weekly_with_price_suffix() -> None:
    plan = parse_subscribe_plan("/subscribe weekly — KES 400")
    assert plan == SubscriptionPlan.WEEKLY


def test_subscribe_without_plan_requires_choice() -> None:
    assert is_bare_subscribe_command("/subscribe")
    assert is_bare_subscribe_command("/subscribe@MoneyLine_bot")
    assert parse_subscribe_plan("/subscribe") is None


def test_plan_choice_text() -> None:
    assert PLAN_CHOICE_PATTERN.match("weekly") is not None
    assert PLAN_CHOICE_PATTERN.match("Monthly").group(1).lower() == "monthly"


def test_subscribe_plan_pattern_allows_trailing_text() -> None:
    match = SUBSCRIBE_PLAN_PATTERN.match("/subscribe monthly — KES 1,200")
    assert match is not None
    assert match.group(1).lower() == "monthly"
