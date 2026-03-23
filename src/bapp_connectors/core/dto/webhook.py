"""
Normalized DTO for webhook events.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from .base import BaseDTO


class WebhookEventType(StrEnum):
    """Normalized webhook event types across all provider families."""

    # Orders
    ORDER_CREATED = "order.created"
    ORDER_UPDATED = "order.updated"
    ORDER_CANCELLED = "order.cancelled"
    ORDER_SHIPPED = "order.shipped"
    ORDER_DELIVERED = "order.delivered"

    # Shipments
    SHIPMENT_CREATED = "shipment.created"
    SHIPMENT_IN_TRANSIT = "shipment.in_transit"
    SHIPMENT_DELIVERED = "shipment.delivered"
    SHIPMENT_FAILED = "shipment.failed"

    # Payments
    PAYMENT_COMPLETED = "payment.completed"
    PAYMENT_FAILED = "payment.failed"
    PAYMENT_REFUNDED = "payment.refunded"

    # Products
    PRODUCT_CREATED = "product.created"
    PRODUCT_UPDATED = "product.updated"
    PRODUCT_DELETED = "product.deleted"

    # Messages
    MESSAGE_RECEIVED = "message.received"
    MESSAGE_DELIVERED = "message.delivered"
    MESSAGE_FAILED = "message.failed"

    # Storage
    FILE_CREATED = "file.created"
    FILE_UPDATED = "file.updated"
    FILE_DELETED = "file.deleted"

    # Generic
    UNKNOWN = "unknown"


class WebhookEvent(BaseDTO):
    """Normalized webhook event after parsing and verification."""

    event_id: str = ""
    event_type: WebhookEventType = WebhookEventType.UNKNOWN
    provider: str = ""
    provider_event_type: str = ""  # original event type from provider
    payload: dict = {}
    idempotency_key: str = ""
    signature_valid: bool | None = None
    received_at: datetime | None = None
    extra: dict = {}
