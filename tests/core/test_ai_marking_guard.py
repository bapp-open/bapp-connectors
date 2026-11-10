"""Guard on the ``@ai_method`` markers of the shop provider clients.

A method marked ``read`` is callable by an external AI agent, server-side, with the company's
marketplace credentials. Every one of them was read down to its HTTP request; the lists below
are that review. Marking a new method ``read`` (or dropping a mark) fails here until the list
is updated, which is the point: the change needs the same review.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
import re

import pytest

import bapp_connectors.providers.shop as shop_pkg
from bapp_connectors.core.ai import AI_ATTR, FORBIDDEN_EXTRA_KEYS, ai_method, ai_methods, drop_method_override
from bapp_connectors.core.registry import registry

for _mod in pkgutil.iter_modules(shop_pkg.__path__):
    if _mod.ispkg:
        importlib.import_module(f"{shop_pkg.__name__}.{_mod.name}")

REVIEWED_READ_METHODS: dict[str, set[str]] = {
    "emag": {
        "get_categories",
        "get_couriers",
        "get_customer_invoices",
        "get_invoice_categories",
        "get_invoices",
        "get_locality",
        "get_order",
        "get_orders",
        "get_product_count",
        "get_products",
        "get_vat_list",
        "read_awb",
        "read_rma",
    },
    "woocommerce": {
        "get_attribute",
        "get_attribute_terms",
        "get_attributes",
        "get_categories",
        "get_order",
        "get_order_status_totals",
        "get_orders",
        "get_product",
        "get_products",
        "get_refunds",
        "get_taxes",
        "get_variation",
        "get_variations",
    },
    "trendyol": {
        "get_batch_result",
        "get_categories",
        "get_claims",
        "get_order",
        "get_orders",
        "get_other_financials",
        "get_products",
        "get_settlements",
    },
    "prestashop": {
        "api_resources",
        "get_address",
        "get_categories",
        "get_combination",
        "get_combinations",
        "get_country",
        "get_images",
        "get_order",
        "get_order_states",
        "get_orders",
        "get_product",
        "get_product_feature",
        "get_product_feature_values",
        "get_product_features",
        "get_product_option_values",
        "get_product_options",
        "get_products",
        "get_state",
        "get_stock_available",
    },
    "altex": {
        "couriers",
        "get_order",
        "get_rma",
        "list_offers",
        "list_orders",
        "list_rmas",
        "localities",
        "locations",
        "regions",
    },
    "gomag": {
        "get_attributes",
        "get_awbs",
        "get_carriers",
        "get_categories",
        "get_customers",
        "get_order",
        "get_order_statuses",
        "get_orders",
        "get_payment_methods",
        "get_products",
    },
    "bapp_store": {
        "export_order",
        "export_orders",
        "find_products",
        "list_categories",
    },
    "cel": {
        "get_categories",
        "get_order",
        "get_orders",
        "get_products",
    },
    "okazii": {
        "get_cities",
        "get_counties",
        "get_countries",
        "get_couriers",
        "get_gdl_awb",
        "get_order",
        "get_order_courier",
        "get_order_invoices",
        "get_orders",
        "get_seller_pickup_address",
    },
    "magento": {
        "get_attribute",
        "get_attribute_options",
        "get_attributes",
        "get_categories",
        "get_category_list",
        "get_configurable_children",
        "get_order",
        "get_orders",
        "get_product",
        "get_product_links",
        "get_products",
        "get_stock_item",
    },
    "shopify": {
        "count_products",
        "get_custom_collections",
        "get_inventory_level",
        "get_order",
        "get_orders",
        "get_product",
        "get_products",
        "get_smart_collections",
        "get_variant",
        "get_variants",
    },
    "temu": {
        "aftersales_detail",
        "get_bill_task",
        "goods_detail",
        "invoice_detail",
        "list_aftersales",
        "list_cancellations",
        "list_carriers",
        "list_goods",
        "list_orders",
        "order_amounts_v2",
        "order_detail",
        "settle_status",
        "shipment_document",
        "shipment_result",
        "shipping_info",
        "shipping_services",
        "sku_stock_query",
        "token_info",
        "warehouses",
    },
    "vendigo": {
        "get_delivery_options",
        "get_groups",
        "get_order",
        "get_orders",
        "get_payment_options",
        "get_product_by_external_id",
        "get_products",
    },
}

# Read methods taking **kwargs: the keys an agent may send through them. Any other read method
# with **kwargs forwards them only to the HTTP layer and must declare nothing.
REVIEWED_READ_EXTRA: dict[tuple[str, str], dict[str, str]] = {
    ("emag", "get_products"): {"params": "flat"},
    ("emag", "read_rma"): {
        "date_start": "scalar",
        "date_end": "scalar",
        "order_id": "scalar",
        "emag_id": "scalar",
        "request_status": "scalar",
    },
    ("woocommerce", "get_orders"): {"params": "flat"},
    ("woocommerce", "get_products"): {"params": "flat"},
    ("trendyol", "get_products"): {"params": "flat"},
    ("gomag", "get_products"): {"params": "flat"},
    ("gomag", "get_orders"): {"params": "flat"},
    ("okazii", "get_orders"): {"params": "flat"},
    ("shopify", "get_products"): {"params": "flat"},
    ("shopify", "get_orders"): {"params": "flat"},
    ("vendigo", "get_orders"): {"params": "flat"},
    ("temu", "list_goods"): {"crtFrom": "scalar", "statusFilterType": "scalar", "goodsSearchType": "scalar"},
}

SHOP_PROVIDERS = sorted(m.name for m in registry.list_providers(family="shop"))


def _dummy_credentials(manifest) -> dict:
    creds = {}
    for f in manifest.auth.required_fields:
        if f.choices:
            creds[f.name] = f.choices[0]
        elif f.default:
            creds[f.name] = f.default
        elif f.role == "endpoint" or any(part in f.name for part in ("url", "domain", "site")):
            creds[f.name] = "https://shop.example.com"
        else:
            creds[f.name] = "dummy"
    return creds


def _adapter(provider: str):
    manifest = registry.get_manifest("shop", provider)
    return registry.create_adapter("shop", provider, credentials=_dummy_credentials(manifest))


def _client_cls(provider: str) -> type:
    return type(_adapter(provider).get_ai_client())


def _read_methods(provider: str):
    cls = _client_cls(provider)
    for name, info in ai_methods(cls).items():
        if info.kind == "read":
            yield name, getattr(cls, name), info


@pytest.mark.parametrize("provider", SHOP_PROVIDERS)
def test_every_shop_adapter_exposes_ai_client(provider):
    """Built with fake credentials (no network), the adapter hands out a client with marks."""
    client = _adapter(provider).get_ai_client()
    assert client is not None
    assert ai_methods(client), f"{provider}: client has no @ai_method marks"
    assert provider in REVIEWED_READ_METHODS, f"{provider}: shop provider missing from the reviewed list"


@pytest.mark.parametrize("provider", SHOP_PROVIDERS)
def test_every_read_method_is_reviewed(provider):
    marked = {name for name, _fn, _info in _read_methods(provider)}
    assert marked == REVIEWED_READ_METHODS[provider]


@pytest.mark.parametrize("provider", SHOP_PROVIDERS)
def test_read_methods_have_annotated_params(provider):
    for name, fn, _info in _read_methods(provider):
        for param in list(inspect.signature(fn).parameters.values())[1:]:
            if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
                continue
            assert param.annotation is not param.empty, f"{provider}.{name}: {param.name} has no annotation"


@pytest.mark.parametrize("provider", SHOP_PROVIDERS)
def test_read_methods_with_var_kwargs_declare_extra(provider):
    for name, fn, info in _read_methods(provider):
        params = inspect.signature(fn).parameters.values()
        has_var_kwargs = any(p.kind is p.VAR_KEYWORD for p in params)
        expected = REVIEWED_READ_EXTRA.get((provider, name), {})
        if not has_var_kwargs:
            assert not expected, f"{provider}.{name}: extra declared but the method takes no **kwargs"
        assert dict(info.extra) == expected, f"{provider}.{name}: extra differs from the reviewed one"
        assert not set(info.extra) & FORBIDDEN_EXTRA_KEYS


@pytest.mark.parametrize("provider", SHOP_PROVIDERS)
def test_no_marked_method_returns_bytes(provider):
    cls = _client_cls(provider)
    for name, info in ai_methods(cls).items():
        returns = inspect.signature(getattr(cls, name)).return_annotation
        text = returns if isinstance(returns, str) else getattr(returns, "__name__", str(returns))
        assert not re.search(r"\b(bytes|bytearray|Response)\b", text), f"{provider}.{name} ({info.kind}) returns {text}"


@pytest.mark.parametrize("provider", SHOP_PROVIDERS)
def test_marks_sit_on_plain_methods_only(provider):
    """`ai_methods` skips a mark put above @staticmethod/@classmethod; none may exist."""
    cls = _client_cls(provider)
    for klass in cls.__mro__:
        for name, value in vars(klass).items():
            if isinstance(value, (staticmethod, classmethod)):
                assert not hasattr(value, AI_ATTR), f"{provider}: {klass.__name__}.{name} mark is ignored"
                assert not hasattr(value.__func__, AI_ATTR), f"{provider}: {klass.__name__}.{name} is not a method"


def test_guard_sees_a_mark_hidden_by_staticmethod():
    class Client:
        @ai_method("read", "Hidden.")
        @staticmethod
        def hidden() -> dict:
            return {}

    assert "hidden" not in ai_methods(Client)
    assert hasattr(vars(Client)["hidden"], AI_ATTR)


@pytest.mark.parametrize(
    ("params", "override", "kept"),
    [
        ({"status": "processing", "_method": "DELETE"}, "_method", {"status": "processing"}),
        ({".method": "DELETE", " _method": "PUT", "_method[]": "DELETE"}, "_method", {}),
        ({"ps_method": "DELETE", "ps.method": "PUT", "display": "full"}, "ps_method", {"display": "full"}),
        ({"_methods": "x", "method": "y"}, "_method", {"_methods": "x", "method": "y"}),
    ],
)
def test_drop_method_override(params, override, kept):
    assert drop_method_override(params, override) == kept


def test_woocommerce_get_never_sends_method_override():
    from bapp_connectors.providers.shop.woocommerce.client import WooCommerceApiClient

    class Http:
        def call(self, method, path, **kwargs):
            self.sent = (method, path, kwargs)
            return []

    http = Http()
    WooCommerceApiClient(http).get_products(params={"_method": "DELETE", "force": "true", "search": "x"})
    assert "_method" not in http.sent[2]["params"]
    assert http.sent[2]["params"]["search"] == "x"


def test_prestashop_get_never_sends_method_override():
    from bapp_connectors.providers.shop.prestashop.client import PrestaShopApiClient

    class Http:
        def call(self, method, path, **kwargs):
            self.sent = (method, path, kwargs)
            return {"orders": []}

    http = Http()
    PrestaShopApiClient(http, token="t", api_url="https://shop.example.com/api/").get_orders(
        {"ps_method": "DELETE", "display": "full"}
    )
    assert "ps_method" not in http.sent[2]["params"]
    assert http.sent[2]["params"]["display"] == "full"


def test_temu_parameters_cannot_replace_the_api_type():
    from bapp_connectors.providers.shop.temu.client import TemuApiClient

    class Http:
        def call(self, method, path, **kwargs):
            self.sent = kwargs["json"]
            return {"success": True, "result": {}}

    http = Http()
    client = TemuApiClient("key", "secret", "token", http_client=http)
    client.list_goods(1, type="temu.local.goods.delete", access_token="other", goodsId=5)
    assert http.sent["type"] == "bg.local.goods.list.query"
    assert http.sent["access_token"] == "token"
