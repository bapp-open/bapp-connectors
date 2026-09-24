"""Optional capability interfaces for feature discovery."""

from .bulk_operations import BulkImportCapability, BulkUpdateCapability, BulkUpsertCapability
from .creative_upload import CreativeUploadCapability
from .dns_allowlist import DnsAllowlistCapability
from .embedding import EmbeddingCapability
from .financial import FinancialCapability
from .image_generation import ImageGenerationCapability
from .inbox import InboxCapability
from .invoice_attach import InvoiceAttachmentCapability
from .mailbox import MailboxCapability
from .oauth import OAuthCapability, OAuthTokens
from .order_lookup import OrderLookupCapability
from .panel_link import PanelLinkCapability
from .product_feed import FeedFormat, FeedUploadCapability, ProductFeedCapability
from .product_lookup import ProductLookupCapability
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
from .settings_detection import SettingsDetectionCapability
from .shipping import ShippingCapability
from .social_publish import SocialPublishCapability
from .streaming import StreamingCapability
from .subscriptions import SubscriptionCapability
from .transcription import TranscriptionCapability
from .volume_pricing import VolumePricingCapability
from .webhooks import WebhookCapability

__all__ = [
    "AttributeManagementCapability",
    "BulkImportCapability",
    "BulkUpdateCapability",
    "BulkUpsertCapability",
    "CategoryManagementCapability",
    "CreativeUploadCapability",
    "DnsAllowlistCapability",
    "EmbeddingCapability",
    "FeedFormat",
    "FeedUploadCapability",
    "FinancialCapability",
    "ImageGenerationCapability",
    "InboxCapability",
    "InvoiceAttachmentCapability",
    "MailboxCapability",
    "OAuthCapability",
    "OAuthTokens",
    "OrderLookupCapability",
    "PanelLinkCapability",
    "ProductCreationCapability",
    "ProductFeedCapability",
    "ProductFullUpdateCapability",
    "ProductLookupCapability",
    "RelatedProductCapability",
    "RichMessagingCapability",
    "SavedPaymentCapability",
    "SettingsDetectionCapability",
    "ShippingCapability",
    "SocialPublishCapability",
    "StreamingCapability",
    "SubscriptionCapability",
    "TranscriptionCapability",
    "VariantManagementCapability",
    "VolumePricingCapability",
    "WebhookCapability",
]
