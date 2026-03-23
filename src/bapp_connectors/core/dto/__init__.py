"""
Normalized data transfer objects for cross-provider communication.
"""

from .base import BaseDTO, BulkResult, ConnectionTestResult, PaginatedResult, ProviderMeta
from .message import DeliveryReport, DeliveryStatus, InboundMessage, MessageChannel, OutboundMessage
from .order import Order, OrderItem, OrderStatus, PaymentStatus, PaymentType
from .partner import Address, Contact
from .payment import CheckoutSession, PaymentMethodType, PaymentResult, Refund
from .product import Product, ProductCategory, ProductPhoto, ProductUpdate, ProductVariant
from .shipment import AWBLabel, Parcel, Shipment, ShipmentStatus, TrackingEvent
from .webhook import WebhookEvent, WebhookEventType

__all__ = [
    "AWBLabel",
    "Address",
    "BaseDTO",
    "BulkResult",
    "CheckoutSession",
    "ConnectionTestResult",
    "Contact",
    "DeliveryReport",
    "DeliveryStatus",
    "InboundMessage",
    "MessageChannel",
    "Order",
    "OrderItem",
    "OrderStatus",
    "OutboundMessage",
    "PaginatedResult",
    "Parcel",
    "PaymentMethodType",
    "PaymentResult",
    "PaymentStatus",
    "PaymentType",
    "Product",
    "ProductCategory",
    "ProductPhoto",
    "ProductUpdate",
    "ProductVariant",
    "ProviderMeta",
    "Refund",
    "Shipment",
    "ShipmentStatus",
    "TrackingEvent",
    "WebhookEvent",
    "WebhookEventType",
]
