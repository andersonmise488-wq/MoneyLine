from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from moneyline.subscriptions.models import SubscriberRecord


@dataclass
class SubscriptionStats:
    active_count: int
    expired_count: int
    pending_count: int
    total_subscribers: int
    total_income_kes: float
    income_today_kes: float
    income_this_month_kes: float
    weekly_active: int
    monthly_active: int
    successful_payments: int
    generated_at: datetime


@dataclass
class DashboardData:
    stats: SubscriptionStats
    active_subscribers: list[SubscriberRecord]
    recent_payments: list[dict]
    recent_subscribers: list[SubscriberRecord]
