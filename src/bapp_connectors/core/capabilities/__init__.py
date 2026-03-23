"""Optional capability interfaces for feature discovery."""

from .bulk_operations import BulkImportCapability, BulkUpdateCapability
from .embedding import EmbeddingCapability
from .image_generation import ImageGenerationCapability
from .invoice_attach import InvoiceAttachmentCapability
from .oauth import OAuthCapability, OAuthTokens
from .product_feed import FeedFormat, ProductFeedCapability
from .product_management import (
    AttributeManagementCapability,
    CategoryManagementCapability,
    ProductCreationCapability,
    ProductFullUpdateCapability,
    RelatedProductCapability,
    VariantManagementCapability,
)
from .streaming import StreamingCapability
from .transcription import TranscriptionCapability
from .webhooks import WebhookCapability

__all__ = [
    "AttributeManagementCapability",
    "BulkImportCapability",
    "BulkUpdateCapability",
    "CategoryManagementCapability",
    "EmbeddingCapability",
    "FeedFormat",
    "ImageGenerationCapability",
    "InvoiceAttachmentCapability",
    "OAuthCapability",
    "OAuthTokens",
    "ProductCreationCapability",
    "ProductFeedCapability",
    "ProductFullUpdateCapability",
    "RelatedProductCapability",
    "StreamingCapability",
    "TranscriptionCapability",
    "VariantManagementCapability",
    "WebhookCapability",
]
