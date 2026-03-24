"""
Normalized data transfer objects for cross-provider communication.
"""

from .base import BaseDTO, BulkResult, ConnectionTestResult, PaginatedResult, ProviderMeta
from .feed import FeedResult, FeedUploadResult, FeedValidationError, FeedValidationResult, FeedWarning
from .llm import (
    ChatMessage,
    ChatRole,
    EmbeddingResult,
    FinishReason,
    ImageResult,
    LLMChunk,
    LLMResponse,
    ModelInfo,
    ModelPricing,
    TokenUsage,
    ToolCall,
    ToolDefinition,
    TranscriptionResult,
)
from .message import DeliveryReport, DeliveryStatus, InboundMessage, MessageChannel, OutboundMessage
from .order import Order, OrderItem, OrderStatus, PaymentStatus, PaymentType
from .partner import Address, Contact
from .payment import CheckoutSession, PaymentMethodType, PaymentResult, Refund
from .product import (
    AttributeDefinition,
    AttributeValue,
    Product,
    ProductAttribute,
    ProductCategory,
    ProductPhoto,
    ProductUpdate,
    ProductVariant,
    RelatedProductLink,
)
from .shipment import AWBLabel, Parcel, Shipment, ShipmentStatus, TrackingEvent
from .webhook import WebhookEvent, WebhookEventType

__all__ = [
    "AWBLabel",
    "Address",
    "AttributeDefinition",
    "AttributeValue",
    "BaseDTO",
    "BulkResult",
    "ChatMessage",
    "ChatRole",
    "CheckoutSession",
    "ConnectionTestResult",
    "Contact",
    "DeliveryReport",
    "DeliveryStatus",
    "EmbeddingResult",
    "FeedResult",
    "FeedUploadResult",
    "FeedValidationError",
    "FeedValidationResult",
    "FeedWarning",
    "FinishReason",
    "ImageResult",
    "InboundMessage",
    "LLMChunk",
    "LLMResponse",
    "MessageChannel",
    "ModelInfo",
    "ModelPricing",
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
    "ProductAttribute",
    "ProductCategory",
    "ProductPhoto",
    "ProductUpdate",
    "ProductVariant",
    "ProviderMeta",
    "Refund",
    "RelatedProductLink",
    "Shipment",
    "ShipmentStatus",
    "TokenUsage",
    "ToolCall",
    "ToolDefinition",
    "TrackingEvent",
    "TranscriptionResult",
    "WebhookEvent",
    "WebhookEventType",
]
