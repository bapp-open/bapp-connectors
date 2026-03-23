"""
Normalized DTOs for orders.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from .base import BaseDTO
from .partner import Address, Contact


class OrderStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    PROCESSING = "processing"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    RETURNED = "returned"
    REFUNDED = "refunded"


class PaymentStatus(StrEnum):
    UNPAID = "unpaid"
    PAID = "paid"
    PARTIALLY_PAID = "partially_paid"
    REFUNDED = "refunded"
    FAILED = "failed"


class PaymentType(StrEnum):
    ONLINE_CARD = "online_card"
    BANK_TRANSFER = "bank_transfer"
    CASH_ON_DELIVERY = "cash_on_delivery"
    PAYMENT_ORDER = "payment_order"
    OTHER = "other"


class OrderItem(BaseDTO):
    """Normalized order line item."""

    item_id: str = ""
    product_id: str = ""
    sku: str = ""
    name: str = ""
    quantity: Decimal = Decimal("1")
    unit_price: Decimal = Decimal("0")
    currency: str = ""
    tax_rate: Decimal | None = None
    discount: Decimal | None = None
    extra: dict = {}


class Order(BaseDTO):
    """Normalized order."""

    order_id: str
    external_id: str | None = None
    status: OrderStatus = OrderStatus.PENDING
    payment_status: PaymentStatus = PaymentStatus.UNPAID
    payment_type: PaymentType | None = None
    currency: str = ""
    items: list[OrderItem] = []
    billing: Contact | None = None
    shipping: Contact | None = None
    shipping_address: Address | None = None
    delivery_address: str = ""
    total: Decimal = Decimal("0")
    created_at: datetime | None = None
    updated_at: datetime | None = None
    external_url: str = ""
    extra: dict = {}
