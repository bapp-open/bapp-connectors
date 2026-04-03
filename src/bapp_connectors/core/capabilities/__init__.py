"""Optional capability interfaces for feature discovery."""

from .bulk_operations import BulkImportCapability, BulkUpdateCapability
from .embedding import EmbeddingCapability
from .image_generation import ImageGenerationCapability
from .inbox import InboxCapability
from .invoice_attach import InvoiceAttachmentCapability
from .oauth import OAuthCapability, OAuthTokens
from .product_feed import FeedFormat, FeedUploadCapability, ProductFeedCapability
from .product_management import (
    AttributeManagementCapability,
    CategoryManagementCapability,
    ProductCreationCapability,
    ProductFullUpdateCapability,
    RelatedProductCapability,
    VariantManagementCapability,
)
from .rich_messaging import RichMessagingCapability
from .saved_payment import SavedPaymentCapability
from .streaming import StreamingCapability
from .subscriptions import SubscriptionCapability
from .transcription import TranscriptionCapability
from .webhooks import WebhookCapability

__all__ = [
    "AttributeManagementCapability",
    "BulkImportCapability",
    "BulkUpdateCapability",
    "CategoryManagementCapability",
    "EmbeddingCapability",
    "FeedFormat",
    "FeedUploadCapability",
    "ImageGenerationCapability",
    "InboxCapability",
    "InvoiceAttachmentCapability",
    "OAuthCapability",
    "OAuthTokens",
    "ProductCreationCapability",
    "ProductFeedCapability",
    "ProductFullUpdateCapability",
    "RelatedProductCapability",
    "RichMessagingCapability",
    "SavedPaymentCapability",
    "StreamingCapability",
    "SubscriptionCapability",
    "TranscriptionCapability",
    "VariantManagementCapability",
    "WebhookCapability",
]
