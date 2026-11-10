"""Guard on the ``@ai_method`` markers of the shop provider clients.

A method marked ``read`` is callable by an external AI agent, server-side, with the company's
marketplace credentials. Every one of them was read down to its HTTP request; the lists below
are that review. Marking a new method ``read`` (or dropping a mark) fails here until the list
is updated, which is the point: the change needs the same review.
"""

from __future__ import annotations

import pytest

from bapp_connectors.core.ai import (
    AI_ATTR,
    PRESTASHOP_BLOCKED_QUERY,
    WOOCOMMERCE_BLOCKED_PREFIXES,
    WOOCOMMERCE_BLOCKED_QUERY,
    ai_method,
    ai_methods,
    drop_method_override,
    drop_query_overrides,
    key_allowed,
)
from tests.core import ai_guard

FAMILY = "shop"
SHOP_PROVIDERS = ai_guard.family_providers(FAMILY)

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

# Shop has no providers left unmarked.
NOT_MARKED: dict[str, str] = {}


def test_every_shop_provider_is_reviewed_or_not_marked():
    ai_guard.check_family_coverage(FAMILY, REVIEWED_READ_METHODS, NOT_MARKED)


def _check(check, provider, **kwargs):
    check(FAMILY, provider, REVIEWED_READ_METHODS, REVIEWED_READ_EXTRA, **kwargs)


@pytest.mark.parametrize("provider", SHOP_PROVIDERS)
def test_every_shop_adapter_exposes_ai_client(provider):
    """Built with fake credentials (no network), the adapter hands out a client with marks."""
    _check(ai_guard.check_exposes_ai_client, provider)


@pytest.mark.parametrize("provider", SHOP_PROVIDERS)
def test_every_read_method_is_reviewed(provider):
    _check(ai_guard.check_read_methods_reviewed, provider)


@pytest.mark.parametrize("provider", SHOP_PROVIDERS)
def test_read_methods_have_annotated_params(provider):
    _check(ai_guard.check_annotated_params, provider)


@pytest.mark.parametrize("provider", SHOP_PROVIDERS)
def test_read_methods_with_var_kwargs_declare_extra(provider):
    _check(ai_guard.check_var_kwargs_extra, provider)


@pytest.mark.parametrize("provider", SHOP_PROVIDERS)
def test_no_marked_method_returns_bytes(provider):
    _check(ai_guard.check_no_bytes_return, provider)


@pytest.mark.parametrize("provider", SHOP_PROVIDERS)
def test_read_methods_return_materialised_data(provider):
    """BAPP refuses lazy results (generators, iterators, awaitables): a read returns its data."""
    _check(ai_guard.check_materialised_data, provider)


# Read params that accept free text (BAPP skips its path-safety check on them). Each one only
# ever reaches a query string or a JSON body, never a URL path.
REVIEWED_FREE_TEXT = {
    ("emag", "get_invoices", "number"),
    ("emag", "get_customer_invoices", "number"),
    ("bapp_store", "find_products", "code"),
    ("trendyol", "get_products", "next_page_token"),
}


@pytest.mark.parametrize("provider", SHOP_PROVIDERS)
def test_free_text_params_are_reviewed(provider):
    _check(ai_guard.check_free_text_reviewed, provider, free_text=REVIEWED_FREE_TEXT)


@pytest.mark.parametrize("provider", SHOP_PROVIDERS)
def test_marks_sit_on_plain_methods_only(provider):
    """`ai_methods` skips a mark put above @staticmethod/@classmethod; none may exist."""
    _check(ai_guard.check_plain_methods_only, provider)


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


@pytest.mark.parametrize("provider", SHOP_PROVIDERS)
def test_marked_method_annotations_resolve_at_runtime(provider):
    """BAPP builds the tool schema from the type hints; a TYPE_CHECKING-only import breaks it."""
    _check(ai_guard.check_annotations_resolve, provider)


# ── allowed_keys: every free-form dict an agent can fill is an allow-list ──

# Temu's signed envelope and call() options; `type` is a legitimate filter elsewhere (WooCommerce).
TEMU_ENVELOPE_KEYS = {"type", "app_key", "access_token", "timestamp", "sign", "sign_method", "retry", "log_body"}


@pytest.mark.parametrize("provider", SHOP_PROVIDERS)
def test_flat_extras_and_dict_params_have_allowed_keys(provider):
    _check(ai_guard.check_dict_params_have_allowed_keys, provider)


@pytest.mark.parametrize("provider", SHOP_PROVIDERS)
def test_allowed_keys_never_list_routing_or_auth_keys(provider):
    blocked = TEMU_ENVELOPE_KEYS if provider == "temu" else set()
    _check(ai_guard.check_allowed_keys_safe, provider, extra_blocked=blocked)


def test_ai_method_requires_allowed_keys_for_flat_extra():
    with pytest.raises(ValueError):
        ai_method("read", "List.", extra={"params": "flat"})
    with pytest.raises(ValueError):
        ai_method("read", "List.", extra={"params": "flat"}, allowed_keys={"params": ()})
    with pytest.raises(ValueError):
        ai_method("read", "List.", extra={"params": "flat"}, allowed_keys={"params": "status"})
    info = ai_method("read", "List.", extra={"params": "flat"}, allowed_keys={"params": ["status", "filter["]})(
        lambda **kw: kw
    ).__bapp_ai__
    assert info.allowed_keys["params"] == ("status", "filter[")
    with pytest.raises(TypeError):
        info.allowed_keys["params"] = ("url",)


def test_key_allowed_exact_and_bracket_prefix():
    assert key_allowed("filter[id]", ("display", "filter["))
    assert key_allowed("display", ("display", "filter["))
    assert not key_allowed("filterx", ("filter[",))
    assert not key_allowed("displays", ("display",))
    assert not key_allowed("url", ("display", "filter["))


# ── Critical 1: PrestaShop `options` cannot switch the webservice resource ──


def _prestashop_sent(options, use_query_auth=False):
    from bapp_connectors.providers.shop.prestashop.client import PrestaShopApiClient

    class Http:
        def call(self, method, path, **kwargs):
            self.sent = (method, path, kwargs)
            return {"orders": []}

    http = Http()
    client = PrestaShopApiClient(
        http, token="key", api_url="https://shop.example.com/api/", use_query_auth=use_query_auth
    )
    client.get_orders(options)
    return http.sent


@pytest.mark.parametrize("use_query_auth", [False, True])
def test_prestashop_options_url_is_dropped_and_not_allowed(use_query_auth):
    from bapp_connectors.providers.shop.prestashop.client import PrestaShopApiClient

    method, path, kwargs = _prestashop_sent(
        {
            "url": "customers",
            "url[]": "employees",
            "ws_key": "other",
            "io_format": "XML",
            "display": "full",
            "filter[id]": "[1|2]",
        },
        use_query_auth,
    )
    params = kwargs["params"]
    assert path.endswith("/api/orders")
    assert "url" not in params and "url[]" not in params
    assert params["display"] == "full" and params["filter[id]"] == "[1|2]"
    if use_query_auth:
        assert params["ws_key"] == "key"  # ours, set after the caller's keys are dropped
    else:
        assert "ws_key" not in params and "io_format" not in params
    allowed = ai_methods(PrestaShopApiClient)["get_orders"].allowed_keys["options"]
    for key in PRESTASHOP_BLOCKED_QUERY:
        assert not key_allowed(key, allowed)


# ── Critical 2: WooCommerce `params` cannot re-route the REST request ──


@pytest.mark.parametrize("use_query_auth", [False, True])
def test_woocommerce_rest_route_is_dropped_and_not_allowed(use_query_auth):
    from bapp_connectors.providers.shop.woocommerce.client import WooCommerceApiClient

    class Http:
        def call(self, method, path, **kwargs):
            self.sent = (method, path, kwargs)
            return []

    http = Http()
    client = WooCommerceApiClient(
        http, consumer_key="ck_ours", consumer_secret="cs_ours", use_query_auth=use_query_auth
    )
    client.get_products(
        params={
            "rest_route": "/wc/v3/webhooks",
            "rest.route": "/wp/v2/users",
            "_jsonp": "cb",
            "_envelope": "1",
            "consumer_key": "ck_other",
            "oauth_token": "x",
            "search": "mug",
        }
    )
    params = http.sent[2]["params"]
    for key in ("rest_route", "rest.route", "_jsonp", "_envelope", "oauth_token"):
        assert key not in params
    assert params["search"] == "mug"
    if use_query_auth:
        assert params["consumer_key"] == "ck_ours"
    else:
        assert "consumer_key" not in params
    for method in ("get_orders", "get_products"):
        allowed = ai_methods(WooCommerceApiClient)[method].allowed_keys["params"]
        for key in WOOCOMMERCE_BLOCKED_QUERY:
            assert not key_allowed(key, allowed)
        assert not any(p.startswith(WOOCOMMERCE_BLOCKED_PREFIXES) for p in allowed)


def test_drop_query_overrides_php_forms():
    params = {"rest_route": 1, " rest_route": 2, "rest.route[]": 3, "Rest_Route": 4, "oauth_nonce": 5, "x": 6}
    assert drop_query_overrides(params, WOOCOMMERCE_BLOCKED_QUERY, WOOCOMMERCE_BLOCKED_PREFIXES) == {"x": 6}


def test_temu_shipping_services_payload_cannot_set_call_options():
    from bapp_connectors.providers.shop.temu.client import TemuApiClient

    class Http:
        def call(self, method, path, **kwargs):
            self.kwargs = kwargs
            return {"success": True, "result": {}}

    http = Http()
    TemuApiClient("key", "secret", "token", http_client=http).shipping_services(
        {"warehouseId": "w", "log_body": True, "retry": False}
    )
    assert "log_body" not in http.kwargs and http.kwargs.get("retry", True) is True
    assert "log_body" not in http.kwargs["json"] and "retry" not in http.kwargs["json"]
