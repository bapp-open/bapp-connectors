"""
Google Merchant Center feed provider manifest.
"""

from bapp_connectors.core.manifest import (
    AuthConfig,
    ProviderManifest,
    SettingsConfig,
    SettingsField,
)
from bapp_connectors.core.ports import FeedPort
from bapp_connectors.core.types import AuthStrategy, FieldType, ProviderFamily

manifest = ProviderManifest(
    name="google_merchant",
    family=ProviderFamily.FEED,
    display_name="Google Merchant Center",
    description="Generate product feeds for Google Shopping / Google Merchant Center.",
    base_url="feed://local",
    auth=AuthConfig(
        strategy=AuthStrategy.NONE,
        required_fields=[],
    ),
    settings=SettingsConfig(
        fields=[
            SettingsField(
                name="base_url",
                label="Shop Base URL",
                field_type=FieldType.STR,
                required=True,
                help_text="Base URL for product links (e.g., https://myshop.ro).",
            ),
            SettingsField(
                name="product_url_template",
                label="Product URL Template",
                field_type=FieldType.STR,
                default="{base_url}/product/{product_id}",
                help_text="URL template for product links. Placeholders: {base_url}, {product_id}, {sku}.",
            ),
            SettingsField(
                name="default_condition",
                label="Default Condition",
                field_type=FieldType.SELECT,
                choices=["new", "refurbished", "used"],
                default="new",
                help_text="Default product condition.",
            ),
            SettingsField(
                name="default_availability",
                label="Default Availability",
                field_type=FieldType.SELECT,
                choices=["in stock", "out of stock", "preorder"],
                default="in stock",
                help_text="Default availability when stock is unknown.",
            ),
            SettingsField(
                name="brand_fallback",
                label="Brand Fallback",
                field_type=FieldType.STR,
                default="",
                help_text="Brand name to use when product has no brand attribute.",
            ),
            SettingsField(
                name="currency",
                label="Currency",
                field_type=FieldType.STR,
                default="RON",
                help_text="ISO 4217 currency code for prices.",
            ),
            SettingsField(
                name="feed_title",
                label="Feed Title",
                field_type=FieldType.STR,
                default="Product Feed",
                help_text="Title element in the feed.",
            ),
            SettingsField(
                name="feed_format",
                label="Feed Format",
                field_type=FieldType.SELECT,
                choices=["xml", "csv"],
                default="xml",
                help_text="Output format for the feed.",
            ),
            SettingsField(
                name="include_variants",
                label="Include Variants",
                field_type=FieldType.BOOL,
                default="true",
                help_text="Expand product variants as separate feed items.",
            ),
        ],
    ),
    capabilities=[FeedPort],
)
