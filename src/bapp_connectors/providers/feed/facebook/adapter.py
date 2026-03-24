"""
Facebook/Meta Commerce feed adapter — implements FeedPort.
"""

from __future__ import annotations

from datetime import UTC, datetime

from bapp_connectors.core.dto.feed import (
    FeedResult,
    FeedValidationError,
    FeedValidationResult,
    FeedWarning,
)
from bapp_connectors.core.dto.product import Product
from bapp_connectors.core.http import ResilientHttpClient
from bapp_connectors.core.ports import FeedPort
from bapp_connectors.providers.feed._utils import expand_variants
from bapp_connectors.providers.feed.facebook.manifest import manifest
from bapp_connectors.providers.feed.facebook.mappers import (
    feed_items_to_csv,
    feed_items_to_xml,
    product_to_feed_item,
    validate_feed_item,
)


class FacebookFeedAdapter(FeedPort):
    """Facebook/Meta Commerce feed generator."""

    manifest = manifest

    def __init__(
        self,
        credentials: dict,
        http_client: ResilientHttpClient | None = None,
        config: dict | None = None,
        **kwargs,
    ):
        self.credentials = credentials
        self.config = config or {}

    # ── BasePort ──

    def validate_credentials(self) -> bool:
        return True

    def test_connection(self):
        from bapp_connectors.core.dto import ConnectionTestResult

        base_url = self.config.get("base_url", "")
        if not base_url:
            return ConnectionTestResult(success=False, message="base_url setting is required")
        return ConnectionTestResult(success=True, message="Facebook Commerce feed generator ready")

    # ── FeedPort ──

    def generate_feed(self, products: list[Product]) -> FeedResult:
        include_variants = str(self.config.get("include_variants", "true")).lower() in ("true", "1", "yes")
        feed_format = self.config.get("feed_format", "csv")
        apparel_mode = str(self.config.get("apparel_mode", "false")).lower() in ("true", "1", "yes")

        valid_items = []
        warnings = []
        skipped = 0

        for product in products:
            expanded = expand_variants(product, include_variants)
            for item_data in expanded:
                feed_item = product_to_feed_item(product, item_data, self.config)
                errors = validate_feed_item(feed_item)

                hard_errors = [e for e in errors if e[2]]
                soft_errors = [e for e in errors if not e[2]]

                if hard_errors:
                    skipped += 1
                    continue

                for field, message, _ in soft_errors:
                    warnings.append(FeedWarning(
                        product_id=feed_item.id,
                        field=field,
                        message=message,
                    ))
                valid_items.append(feed_item)

        if feed_format == "xml":
            content = feed_items_to_xml(valid_items, self.config)
            content_type = "application/xml"
        else:
            content = feed_items_to_csv(valid_items, apparel_mode)
            content_type = "text/csv"

        return FeedResult(
            content=content,
            format=feed_format,
            content_type=content_type,
            product_count=len(valid_items),
            skipped_count=skipped,
            warnings=warnings,
            generated_at=datetime.now(UTC),
        )

    def validate_products(self, products: list[Product]) -> FeedValidationResult:
        include_variants = str(self.config.get("include_variants", "true")).lower() in ("true", "1", "yes")
        errors = []
        valid = 0
        invalid = 0

        for product in products:
            expanded = expand_variants(product, include_variants)
            for item_data in expanded:
                feed_item = product_to_feed_item(product, item_data, self.config)
                item_errors = validate_feed_item(feed_item)
                if any(e[2] for e in item_errors):
                    invalid += 1
                    for field, message, required in item_errors:
                        errors.append(FeedValidationError(
                            product_id=feed_item.id,
                            field=field,
                            message=message,
                            required=required,
                        ))
                else:
                    valid += 1

        return FeedValidationResult(valid_count=valid, invalid_count=invalid, errors=errors)

    def supported_formats(self) -> list[str]:
        return ["csv", "xml"]
