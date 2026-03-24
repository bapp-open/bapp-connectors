"""
Okazii.ro feed provider manifest.

Okazii uses XML feeds for product import. The shop hosts the feed,
and Okazii polls it daily for automatic synchronization.
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
    name="okazii",
    family=ProviderFamily.FEED,
    display_name="Okazii.ro",
    description="Generate product feeds for Okazii.ro Romanian marketplace.",
    base_url="feed://local",
    auth=AuthConfig(
        strategy=AuthStrategy.NONE,
        required_fields=[],
    ),
    settings=SettingsConfig(
        fields=[
            # ── Product defaults ──
            SettingsField(
                name="currency",
                label="Currency",
                field_type=FieldType.STR,
                default="RON",
                help_text="Currency code for prices.",
            ),
            SettingsField(
                name="default_condition",
                label="Default Condition",
                field_type=FieldType.SELECT,
                choices=["1", "2"],
                default="1",
                help_text="Product condition: 1=New, 2=Used.",
            ),
            SettingsField(
                name="brand_fallback",
                label="Brand Fallback",
                field_type=FieldType.STR,
                default="",
                help_text="Brand name when product has no brand attribute.",
            ),
            SettingsField(
                name="invoice",
                label="Invoice Available",
                field_type=FieldType.SELECT,
                choices=["1", "2"],
                default="1",
                help_text="Products have invoice: 1=Yes, 2=No.",
            ),
            SettingsField(
                name="warranty",
                label="Warranty Available",
                field_type=FieldType.SELECT,
                choices=["1", "2"],
                default="1",
                help_text="Products have warranty: 1=Yes, 2=No.",
            ),
            # ── Payment ──
            SettingsField(
                name="payment_personal",
                label="Cash on Pickup",
                field_type=FieldType.BOOL,
                default="false",
                help_text="Accept cash on pickup.",
            ),
            SettingsField(
                name="payment_ramburs",
                label="Cash on Delivery",
                field_type=FieldType.BOOL,
                default="true",
                help_text="Accept cash on delivery (ramburs).",
            ),
            SettingsField(
                name="payment_avans",
                label="Bank Transfer",
                field_type=FieldType.BOOL,
                default="true",
                help_text="Accept bank transfer / prepayment.",
            ),
            # ── Delivery ──
            SettingsField(
                name="delivery_time",
                label="Delivery Time (days)",
                field_type=FieldType.INT,
                default="3",
                help_text="Default delivery time in days.",
            ),
            SettingsField(
                name="courier_name",
                label="Courier Name",
                field_type=FieldType.STR,
                default="",
                help_text="Default courier name (e.g., Fan Courier, Sameday).",
            ),
            SettingsField(
                name="courier_price",
                label="Shipping Cost",
                field_type=FieldType.STR,
                default="",
                help_text="Default shipping cost (e.g., 15.99).",
            ),
            # ── Return policy ──
            SettingsField(
                name="return_accept",
                label="Accept Returns",
                field_type=FieldType.BOOL,
                default="true",
                help_text="Accept product returns.",
            ),
            SettingsField(
                name="return_days",
                label="Return Window (days)",
                field_type=FieldType.INT,
                default="14",
                help_text="Number of days for returns.",
            ),
            # ── Variants ──
            SettingsField(
                name="include_variants",
                label="Include Variants as Stocks",
                field_type=FieldType.BOOL,
                default="true",
                help_text="Map product variants to Okazii STOCKS section (Size/Color).",
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
                help_text="Comma-separated list of category names to exclude from the feed.",
            ),
        ],
    ),
    capabilities=[FeedPort],
)
