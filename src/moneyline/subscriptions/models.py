from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class SubscriptionPlan(str, Enum):
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class SubscriberRecord(BaseModel):
    id: int
    telegram_chat_id: str
    telegram_username: str | None = None
    phone: str | None = None
    plan: SubscriptionPlan | None = None
    status: str
    expires_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
