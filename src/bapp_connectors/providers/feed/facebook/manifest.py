"""
Facebook/Meta Commerce feed provider manifest.
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
    name="facebook",
    family=ProviderFamily.FEED,
    display_name="Facebook Commerce",
    description="Generate product feeds for Facebook Marketplace / Meta Commerce catalog.",
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
                name="brand_fallback",
                label="Brand Fallback",
                field_type=FieldType.STR,
                default="",
                help_text="Brand name when product has no brand attribute.",
            ),
            SettingsField(
                name="currency",
                label="Currency",
                field_type=FieldType.STR,
                default="RON",
                help_text="ISO 4217 currency code.",
            ),
            SettingsField(
                name="feed_format",
                label="Feed Format",
                field_type=FieldType.SELECT,
                choices=["csv", "xml"],
                default="csv",
                help_text="Output format for the feed.",
            ),
            SettingsField(
                name="include_variants",
                label="Include Variants",
                field_type=FieldType.BOOL,
                default="true",
                help_text="Expand product variants as separate feed items.",
            ),
            SettingsField(
                name="apparel_mode",
                label="Apparel Mode",
                field_type=FieldType.BOOL,
                default="false",
                help_text="Include gender, age_group, color, size fields for apparel products.",
            ),
            # ── Filters ──
            SettingsField(
                name="only_in_stock",
                label="Only In-Stock Products",
                field_type=FieldType.BOOL,
                default="false",
                help_text="Exclude products that are out of stock.",
            ),
            SettingsField(
                name="categories_exclude",
                label="Exclude Categories",
                field_type=FieldType.STR,
                default="",
                help_text="Comma-separated list of category IDs to exclude from the feed.",
            ),
        ],
    ),
    capabilities=[FeedPort],
)
