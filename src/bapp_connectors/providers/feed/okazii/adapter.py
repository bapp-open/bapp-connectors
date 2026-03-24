"""
Okazii.ro feed adapter — implements FeedPort.

Generates XML feeds in Okazii's custom format with <OKAZII>/<AUCTION> structure,
including payment, delivery, return policy, attributes, and stock variants.
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
from bapp_connectors.providers.feed._utils import filter_products
from bapp_connectors.providers.feed.okazii.manifest import manifest
from bapp_connectors.providers.feed.okazii.mappers import (
    feed_items_to_xml,
    product_to_feed_item,
    validate_feed_item,
)


class OkaziiFeedAdapter(FeedPort):
    """Okazii.ro feed generator.

    Produces Okazii-compatible XML with full AUCTION structure including
    payment methods, delivery options, return policies, attributes, and
    stock variants (STOCKS section for Size/Color).
    """

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

        return ConnectionTestResult(success=True, message="Okazii.ro feed generator ready")

    # ── FeedPort ──

    def generate_feed(self, products: list[Product]) -> FeedResult:
        products = filter_products(products, self.config)
        valid_items = []
        warnings = []
        skipped = 0

        for product in products:
            feed_item = product_to_feed_item(product, self.config)
            errors = validate_feed_item(feed_item)

            hard_errors = [e for e in errors if e[2]]
            soft_errors = [e for e in errors if not e[2]]

            if hard_errors:
                skipped += 1
                continue

            for field, message, _ in soft_errors:
                warnings.append(FeedWarning(
                    product_id=feed_item.unique_id,
                    field=field,
                    message=message,
                ))
            valid_items.append(feed_item)

        content = feed_items_to_xml(valid_items)

        return FeedResult(
            content=content,
            format="xml",
            content_type="application/xml",
            product_count=len(valid_items),
            skipped_count=skipped,
            warnings=warnings,
            generated_at=datetime.now(UTC),
        )

    def validate_products(self, products: list[Product]) -> FeedValidationResult:
        products = filter_products(products, self.config)
        errors = []
        valid = 0
        invalid = 0

        for product in products:
            feed_item = product_to_feed_item(product, self.config)
            item_errors = validate_feed_item(feed_item)
            if any(e[2] for e in item_errors):
                invalid += 1
                for field, message, required in item_errors:
                    errors.append(FeedValidationError(
                        product_id=feed_item.unique_id,
                        field=field,
                        message=message,
                        required=required,
                    ))
            else:
                valid += 1

        return FeedValidationResult(valid_count=valid, invalid_count=invalid, errors=errors)

    def supported_formats(self) -> list[str]:
        return ["xml"]
