from __future__ import annotations

from datetime import datetime, timedelta, timezone

from moneyline.config.settings import get_settings
from moneyline.subscriptions.models import SubscriptionPlan


def plan_amount(plan: SubscriptionPlan) -> int:
    settings = get_settings()
    if plan == SubscriptionPlan.WEEKLY:
        return int(settings.subscription_weekly_kes)
    return int(settings.subscription_monthly_kes)


def plan_label(plan: SubscriptionPlan) -> str:
    return "Weekly" if plan == SubscriptionPlan.WEEKLY else "Monthly"


def plan_duration(plan: SubscriptionPlan) -> timedelta:
    if plan == SubscriptionPlan.WEEKLY:
        return timedelta(days=7)
    return timedelta(days=30)


def extend_expiry(current: datetime | None, plan: SubscriptionPlan) -> datetime:
    now = datetime.now(timezone.utc)
    base = current if current and current > now else now
    return base + plan_duration(plan)


def display_phone(phone: str) -> str:
    """254712345678 → 0712345678 for till STK entry."""
    digits = "".join(ch for ch in phone if ch.isdigit())
    if digits.startswith("254") and len(digits) == 12:
        return "0" + digits[3:]
    return phone


def normalize_phone(raw: str) -> str:
    digits = "".join(ch for ch in raw if ch.isdigit())
    if digits.startswith("0") and len(digits) == 10:
        return "254" + digits[1:]
    if digits.startswith("254") and len(digits) == 12:
        return digits
    if digits.startswith("7") and len(digits) == 9:
        return "254" + digits
    raise ValueError("Use a Kenyan number like 0712345678 or 254712345678")
