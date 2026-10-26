"""Optional capability interfaces for feature discovery."""

from .batch_tracking import BatchTrackingCapability
from .bulk_operations import BulkImportCapability, BulkUpdateCapability, BulkUpsertCapability
from .creative_upload import CreativeUploadCapability
from .customer_details import CustomerDetailsCapability
from .dns_allowlist import DnsAllowlistCapability
from .embedding import EmbeddingCapability
from .financial import FinancialCapability
from .fulfillment import Carrier, FulfillmentCapability, ShipmentResult, ShippingService
from .image_generation import ImageGenerationCapability
from .inbox import InboxCapability
from .invoice_attach import InvoiceAttachmentCapability
from .issue_management import IssueManagementCapability
from .issue_triage import IssueTriageCapability
from .mailbox import MailboxCapability
from .oauth import OAuthCapability, OAuthTokens
from .order_amounts import OrderAmountCapability, OrderAmounts, OrderLineAmounts
from .order_lookup import OrderLookupCapability
from .order_payment import OrderPaymentCapability
from .order_status_catalog import OrderStatusCatalogCapability, RemoteOrderStatus
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
from .project_provisioning import ProjectProvisioningCapability
from .returns import ReturnsCapability
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
    "BatchTrackingCapability",
    "BulkImportCapability",
    "BulkUpdateCapability",
    "BulkUpsertCapability",
    "Carrier",
    "CategoryManagementCapability",
    "CreativeUploadCapability",
    "CustomerDetailsCapability",
    "DnsAllowlistCapability",
    "EmbeddingCapability",
    "FeedFormat",
    "FeedUploadCapability",
    "FinancialCapability",
    "FulfillmentCapability",
    "ImageGenerationCapability",
    "InboxCapability",
    "InvoiceAttachmentCapability",
    "IssueManagementCapability",
    "IssueTriageCapability",
    "MailboxCapability",
    "OAuthCapability",
    "OAuthTokens",
    "OrderAmountCapability",
    "OrderAmounts",
    "OrderLineAmounts",
    "OrderLookupCapability",
    "OrderPaymentCapability",
    "OrderStatusCatalogCapability",
    "PanelLinkCapability",
    "ProductCreationCapability",
    "ProductFeedCapability",
    "ProductFullUpdateCapability",
    "ProductLookupCapability",
    "ProjectProvisioningCapability",
    "RelatedProductCapability",
    "RemoteOrderStatus",
    "ReturnsCapability",
    "RichMessagingCapability",
    "SavedPaymentCapability",
    "SettingsDetectionCapability",
    "ShipmentResult",
    "ShippingCapability",
    "ShippingService",
    "SocialPublishCapability",
    "StreamingCapability",
    "SubscriptionCapability",
    "TranscriptionCapability",
    "VariantManagementCapability",
    "VolumePricingCapability",
    "WebhookCapability",
]
