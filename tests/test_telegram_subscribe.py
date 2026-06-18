"""Telegram /subscribe command parsing."""

from moneyline.bot.telegram_bot import PLAN_CHOICE_PATTERN, PLAN_PATTERN


def test_subscribe_weekly_command() -> None:
    match = PLAN_PATTERN.match("/subscribe weekly")
    assert match is not None
    assert match.group(1).lower() == "weekly"


def test_subscribe_weekly_with_bot_username() -> None:
    match = PLAN_PATTERN.match("/subscribe@MoneyLine_bot weekly")
    assert match is not None
    assert match.group(1).lower() == "weekly"


def test_subscribe_without_plan_requires_choice() -> None:
    match = PLAN_PATTERN.match("/subscribe")
    assert match is not None
    assert match.group(1) is None


def test_plan_choice_while_awaiting_phone() -> None:
    assert PLAN_CHOICE_PATTERN.match("weekly") is not None
    assert PLAN_CHOICE_PATTERN.match("Monthly").group(1).lower() == "monthly"
