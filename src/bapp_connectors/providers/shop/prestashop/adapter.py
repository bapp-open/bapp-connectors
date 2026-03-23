"""
PrestaShop shop adapter — implements ShopPort.

This is the main entry point for the PrestaShop integration.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bapp_connectors.core.dto import (
    ConnectionTestResult,
    Order,
    PaginatedResult,
    Product,
)
from bapp_connectors.core.http import ResilientHttpClient
from bapp_connectors.core.ports import ShopPort
from bapp_connectors.providers.shop.prestashop.client import PrestaShopApiClient
from bapp_connectors.providers.shop.prestashop.manifest import manifest
from bapp_connectors.providers.shop.prestashop.mappers import (
    PRESTASHOP_PERMISSIONS_REQUIRED,
    order_from_prestashop,
    orders_from_prestashop,
    products_from_prestashop,
)

if TYPE_CHECKING:
    from datetime import datetime
    from decimal import Decimal


class PrestaShopShopAdapter(ShopPort):
    """
    PrestaShop webservice adapter.

    Implements:
    - ShopPort: orders, products, stock/price updates
    """

    manifest = manifest

    def __init__(self, credentials: dict, http_client: ResilientHttpClient | None = None, **kwargs):
        self.credentials = credentials
        self._api_url = self._build_api_url(credentials.get("domain", ""))

        if http_client is None:
            from bapp_connectors.core.http import NoAuth

            http_client = ResilientHttpClient(
                base_url=self._api_url,
                auth=NoAuth(),  # PrestaShop uses basic auth with API key; handled in client
                provider_name="prestashop",
            )

        self.client = PrestaShopApiClient(
            http_client=http_client,
            token=credentials.get("token", ""),
        )

    @staticmethod
    def _build_api_url(domain: str) -> str:
        """Build the API URL from the shop domain."""
        domain = domain.rstrip("/")
        if domain.endswith("/api"):
            return domain + "/"
        return domain + "/api/"

    # ── BasePort ──

    def validate_credentials(self) -> bool:
        missing = self.manifest.auth.validate_credentials(self.credentials)
        return len(missing) == 0

    def test_connection(self) -> ConnectionTestResult:
        try:
            result = self.client.test_auth()
            if not result:
                return ConnectionTestResult(success=False, message="Authentication failed")

            # Verify that all required permissions are available
            api_resources = result.get("api", {})
            if api_resources:
                missing_perms = [perm for perm in PRESTASHOP_PERMISSIONS_REQUIRED if perm not in api_resources]
                if missing_perms:
                    return ConnectionTestResult(
                        success=False,
                        message=f"Missing API permissions: {', '.join(missing_perms)}",
                        details={"missing_permissions": missing_perms},
                    )

            return ConnectionTestResult(success=True, message="Connection successful")
        except Exception as e:
            return ConnectionTestResult(success=False, message=str(e))

    # ── ShopPort ──

    def get_orders(self, since: datetime | None = None, cursor: str | None = None) -> PaginatedResult[Order]:
        options: dict = {"display": "full"}
        if since:
            start_time = since.strftime("%Y-%m-%d %H:%M:%S")
            options["filter[date_add]"] = f"[{start_time},]"
            options["date"] = "1"

        raw_orders = self.client.get_orders(options=options)
        mapped_orders = []
        for raw_order in raw_orders:
            enriched = self._enrich_order(raw_order)
            mapped_orders.append(enriched)

        return orders_from_prestashop(mapped_orders)

    def get_order(self, order_id: str) -> Order:
        data = self.client.get_order(int(order_id))
        return self._enrich_order(data)

    def _enrich_order(self, order_data: dict) -> Order:
        """Fetch related address/customer data and map to Order DTO."""
        delivery_address = {}
        invoice_address = {}
        customer = {}
        delivery_country_iso = ""
        delivery_state_name = ""
        invoice_country_iso = ""
        invoice_state_name = ""

        # Fetch delivery address
        if addr_id := order_data.get("id_address_delivery"):
            delivery_address = self.client.get_address(int(addr_id))
            if country_id := delivery_address.get("id_country"):
                country = self.client.get_country(int(country_id))
                delivery_country_iso = country.get("iso_code", "")
            if (state_id := delivery_address.get("id_state")) and int(state_id):
                state = self.client.get_state(int(state_id))
                delivery_state_name = state.get("name", "")

        # Fetch invoice address
        if addr_id := order_data.get("id_address_invoice"):
            invoice_address = self.client.get_address(int(addr_id))
            if country_id := invoice_address.get("id_country"):
                country = self.client.get_country(int(country_id))
                invoice_country_iso = country.get("iso_code", "")
            if (state_id := invoice_address.get("id_state")) and int(state_id):
                state = self.client.get_state(int(state_id))
                invoice_state_name = state.get("name", "")

        # Fetch customer
        if customer_id := order_data.get("id_customer"):
            customer = self.client.get_customer(int(customer_id))

        return order_from_prestashop(
            data=order_data,
            delivery_address=delivery_address,
            invoice_address=invoice_address,
            customer=customer,
            delivery_country_iso=delivery_country_iso,
            delivery_state_name=delivery_state_name,
            invoice_country_iso=invoice_country_iso,
            invoice_state_name=invoice_state_name,
        )

    def get_products(self, cursor: str | None = None) -> PaginatedResult[Product]:
        page = int(cursor) if cursor else 1
        per_page = 100
        offset = (page - 1) * per_page

        options = {
            "display": "full",
            "limit": f"{offset},{per_page}",
        }
        results = self.client.get_products(options=options)
        paginated = products_from_prestashop(results)

        # Set cursor for next page if we got a full page of results
        if len(results) >= per_page:
            paginated = PaginatedResult(
                items=paginated.items,
                cursor=str(page + 1),
                has_more=True,
                total=paginated.total,
            )

        return paginated

    def update_product_stock(self, product_id: str, quantity: int) -> None:
        self.client.update_stock_available(
            data={"stock_available": {"id_product": product_id, "quantity": quantity}},
        )

    def update_product_price(self, product_id: str, price: Decimal, currency: str) -> None:
        # PrestaShop product price updates require the full product XML/JSON payload
        # This is a simplified version that updates via the products endpoint
        product_data = self.client.get_product(int(product_id))
        if product_data:
            product_data["price"] = str(price)
            # Note: Full implementation would need to handle PrestaShop's XML edit format
            raise NotImplementedError(
                "PrestaShop price update requires the prestapyt library's edit method. "
                "Use the daily_sync workflow for batch price updates."
            )
