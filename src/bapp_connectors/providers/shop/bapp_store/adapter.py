"""
Company Store (BAPP) shop adapter: pushes the BAPP catalogue into a tenant store through
CatalogSyncTask and reads orders back through the export tasks.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC
from decimal import Decimal
from typing import TYPE_CHECKING

from bapp_connectors.core.capabilities import (
    BulkUpsertCapability,
    CategoryManagementCapability,
    ProductCreationCapability,
    ProductFullUpdateCapability,
    ProductLookupCapability,
    VolumePricingCapability,
    WebhookCapability,
)
from bapp_connectors.core.dto import (
    BulkUpsertResult,
    ConnectionTestResult,
    Order,
    OrderStatus,
    PaginatedResult,
    Product,
    ProductCategory,
    ProductUpdate,
    ShopRules,
    WebhookEvent,
    WebhookEventType,
)
from bapp_connectors.core.errors import ConnectorError, PermanentProviderError, UnsupportedFeatureError
from bapp_connectors.core.ports import ShopPort
from bapp_connectors.providers.shop.bapp_store.client import BappStoreClient
from bapp_connectors.providers.shop.bapp_store.manifest import manifest
from bapp_connectors.providers.shop.bapp_store.mappers import (
    bulk_result_from_response,
    category_from_store,
    category_record,
    order_from_store,
    orders_page_from_store,
    product_from_store,
    product_to_record,
    rules_to_body,
    update_to_record,
)
from bapp_connectors.providers.shop.bapp_store.models import SyncTaskResponse

if TYPE_CHECKING:
    from datetime import datetime

SIGNATURE_HEADER = "X-BappStore-Signature"

_WEBHOOK_EVENTS = {
    "order.created": WebhookEventType.ORDER_CREATED,
    "order.updated": WebhookEventType.ORDER_UPDATED,
}


class BappStoreShopAdapter(
    ShopPort,
    BulkUpsertCapability,
    ProductCreationCapability,
    ProductFullUpdateCapability,
    ProductLookupCapability,
    CategoryManagementCapability,
    VolumePricingCapability,
    WebhookCapability,
):
    manifest = manifest
    max_batch_size = 100
    sideloads_images = False
    supports_modified_since = False
    accepts_local_category_id = True

    def __init__(self, credentials: dict, http_client=None, config: dict | None = None, **kwargs):
        self.credentials = credentials
        config = config or {}
        self.store_url = credentials.get("store_url", "")
        self.token = credentials.get("token", "")
        self._vat_rate = Decimal(str(config.get("vat_rate", "0.21")))
        self.client = BappStoreClient(self.store_url, self.token, http_client=http_client)

    # -- BasePort --

    def validate_credentials(self) -> bool:
        return not self.manifest.auth.validate_credentials(self.credentials)

    def test_connection(self) -> ConnectionTestResult:
        try:
            ok = self.client.test_auth()
        except ConnectorError as e:
            return ConnectionTestResult(success=False, message=str(e))
        return ConnectionTestResult(success=ok, message="Connection successful" if ok else "Authentication failed")

    # -- Products --

    def get_products(self, cursor: str | None = None, since: datetime | None = None) -> PaginatedResult[Product]:
        page = int(cursor) if cursor else 1
        data = self.client.find_products(page=page)
        has_more = bool(data.get("next"))
        return PaginatedResult(
            items=[product_from_store(row, self._vat_rate) for row in data.get("results", [])],
            cursor=str(page + 1) if has_more else None,
            has_more=has_more,
            total=data.get("count"),
        )

    def find_product_by_sku(self, sku: str) -> Product | None:
        if not sku:
            return None
        data = self.client.find_products(code=sku)
        # `code` is a declared filterset field on the store viewset, but the loop stays: only an exact match is an adoption candidate.
        for row in data.get("results", []):
            if row.get("code") == sku:
                return product_from_store(row, self._vat_rate)
        return None

    def bulk_upsert_products(self, creates: list[Product], updates: list[ProductUpdate]) -> BulkUpsertResult:
        total = len(creates) + len(updates)
        if total == 0:
            return BulkUpsertResult()
        if total > self.max_batch_size:
            raise ValueError(f"CatalogSyncTask accepts at most {self.max_batch_size} products, got {total}")
        records = [product_to_record(p, self._vat_rate) for p in creates] + [update_to_record(u, self._vat_rate) for u in updates]
        response = self.client.sync_task({"products": records})
        return bulk_result_from_response(
            response, len(creates), len(updates), [p.product_id for p in creates], [u.product_id for u in updates],
        )

    def create_product(self, product: Product) -> Product:
        result = self.bulk_upsert_products([product], [])
        self._raise_single(result.created, product.product_id)
        return product

    def update_product(self, update: ProductUpdate) -> None:
        result = self.bulk_upsert_products([], [update])
        self._raise_single(result.updated, update.product_id)

    @staticmethod
    def _raise_single(items, product_id: str) -> None:
        if not items:
            raise PermanentProviderError(f"no result returned for product {product_id}")
        if items[0].error:
            raise PermanentProviderError(items[0].error, code=items[0].error_code)

    def delete_product(self, product_id: str) -> None:
        raise UnsupportedFeatureError("bapp_store never prunes products; deactivate them instead")

    def update_product_stock(self, product_id: str, quantity: int) -> None:
        raise UnsupportedFeatureError("bapp_store updates stock through bulk_upsert_products")

    def update_product_price(self, product_id: str, price: Decimal, currency: str) -> None:
        raise UnsupportedFeatureError("bapp_store updates prices through bulk_upsert_products")

    # -- Categories --

    def get_categories(self) -> list[ProductCategory]:
        categories = [category_from_store(row) for row in self.client.list_categories()]
        by_store_id = {c.extra["store_id"]: c.category_id for c in categories}
        return [c.model_copy(update={"parent_id": by_store_id.get(c.parent_id, c.parent_id)}) for c in categories]

    def create_category(self, name: str, parent_id: str | None = None, local_id: str | None = None) -> ProductCategory:
        if not local_id:
            raise ValueError("bapp_store categories are keyed by the BAPP category id; local_id is required")
        response = self.client.sync_task({"categories": [category_record(name, parent_id, local_id)]})
        self._raise_category(response, local_id)
        return ProductCategory(category_id=local_id, name=name, parent_id=parent_id)

    def update_category(self, category: ProductCategory) -> ProductCategory:
        # Name and parent only (spec 2.2): a store-side activation toggle is not BAPP's to overwrite on a rename.
        response = self.client.sync_task({"categories": [category_record(category.name, category.parent_id, category.category_id, is_active=None)]})
        self._raise_category(response, category.category_id)
        return category

    @staticmethod
    def _raise_category(response: dict, local_id: str) -> None:
        items = SyncTaskResponse.model_validate(response).categories
        if not items:
            raise PermanentProviderError(f"no result returned for category {local_id}")
        if items[0].error:
            raise PermanentProviderError(items[0].error, code=items[0].code)

    # -- Volume pricing --

    def push_shop_rules(self, rules: ShopRules) -> None:
        response = self.client.sync_task({"rules": rules_to_body(rules)})
        if not SyncTaskResponse.model_validate(response).rules_applied:
            raise PermanentProviderError("store did not apply the pricing rules")

    # -- Orders --

    def get_orders(self, since: datetime | None = None, cursor: str | None = None) -> PaginatedResult[Order]:
        since_iso = None
        if since is not None:
            if since.tzinfo is None:
                since = since.replace(tzinfo=UTC)
            since_iso = since.isoformat()
        return orders_page_from_store(self.client.export_orders(since=since_iso, cursor=cursor), self._vat_rate)

    def get_order(self, order_id: str) -> Order:
        return order_from_store(self.client.export_order(order_id), self._vat_rate)

    def update_order_status(self, order_id: str, status: OrderStatus) -> Order:
        raise UnsupportedFeatureError("bapp_store does not accept order status updates")

    # -- Webhooks --

    def verify_webhook(self, headers: dict, body: bytes, secret: str = "") -> bool:
        signature = next((v for k, v in headers.items() if k.lower() == SIGNATURE_HEADER.lower()), "")
        if not signature or not secret:
            return False
        computed = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        # compare_digest raises TypeError on non-ASCII str operands, and the header is attacker-controlled.
        return hmac.compare_digest(signature.lower().encode("utf-8"), computed.encode("utf-8"))

    def parse_webhook(self, headers: dict, body: bytes) -> WebhookEvent:
        data = json.loads(body)
        event = str(data.get("event", ""))
        order_id = str(data.get("id", ""))
        key = f"{event}:{order_id}"
        return WebhookEvent(
            event_id=key,
            event_type=_WEBHOOK_EVENTS.get(event, WebhookEventType.UNKNOWN),
            provider="bapp_store",
            provider_event_type=event,
            payload={"id": order_id},
            idempotency_key=key,
        )
