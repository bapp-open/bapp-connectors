"""
Compari.ro feed provider manifest.
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
    name="compari",
    family=ProviderFamily.FEED,
    display_name="Compari.ro",
    description="Generate product feeds for Compari.ro Romanian price comparison platform.",
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
                name="manufacturer_fallback",
                label="Manufacturer Fallback",
                field_type=FieldType.STR,
                default="",
                help_text="Manufacturer name when product has no brand/manufacturer attribute.",
            ),
            SettingsField(
                name="currency",
                label="Currency",
                field_type=FieldType.STR,
                default="RON",
                help_text="Currency code for prices.",
            ),
            SettingsField(
                name="default_delivery_time",
                label="Default Delivery Time",
                field_type=FieldType.STR,
                default="",
                help_text="Default delivery time (e.g., '1-3 zile').",
            ),
            SettingsField(
                name="default_delivery_cost",
                label="Default Delivery Cost",
                field_type=FieldType.STR,
                default="",
                help_text="Default delivery cost (e.g., '15.99').",
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
