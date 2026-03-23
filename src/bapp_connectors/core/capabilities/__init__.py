"""Optional capability interfaces for feature discovery."""

from .bulk_operations import BulkImportCapability, BulkUpdateCapability
from .invoice_attach import InvoiceAttachmentCapability
from .oauth import OAuthCapability, OAuthTokens
from .product_feed import FeedFormat, ProductFeedCapability
from .webhooks import WebhookCapability

__all__ = [
    "BulkImportCapability",
    "BulkUpdateCapability",
    "FeedFormat",
    "InvoiceAttachmentCapability",
    "OAuthCapability",
    "OAuthTokens",
    "ProductFeedCapability",
    "WebhookCapability",
]
