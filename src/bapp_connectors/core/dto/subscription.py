"""
Normalized DTOs for subscription operations.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from .base import BaseDTO


class SubscriptionInterval(StrEnum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    YEAR = "year"


class SubscriptionStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    PENDING = "pending"
    PAST_DUE = "past_due"
    TRIALING = "trialing"
    UNPAID = "unpaid"


class Subscription(BaseDTO):
    """A recurring subscription."""

    subscription_id: str
    status: SubscriptionStatus
    customer_id: str = ""
    price_id: str = ""
    amount: Decimal = Decimal("0")
    currency: str = ""
    interval: SubscriptionInterval = SubscriptionInterval.MONTH
    interval_count: int = 1
    current_period_start: datetime | None = None
    current_period_end: datetime | None = None
    cancel_at_period_end: bool = False
    cancelled_at: datetime | None = None
    trial_start: datetime | None = None
    trial_end: datetime | None = None
    created_at: datetime | None = None
    extra: dict = {}
