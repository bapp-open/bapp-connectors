"""bapp_store adapter tests against FakeHttpClient; no store needed."""
from __future__ import annotations

import hashlib
import hmac
import json
from decimal import Decimal
from importlib.resources import files

import pytest

from bapp_connectors.core.dto import (
    OrderValueTier,
    Product,
    ProductCategory,
    ProductUpdate,
    ShopRules,
    WebhookEventType,
)
from bapp_connectors.core.errors import PermanentProviderError, ProviderError, UnsupportedFeatureError
from bapp_connectors.providers.shop.bapp_store.adapter import BappStoreShopAdapter
from tests.fake_http import FakeHttpClient
from tests.shop.bapp_store.fake_response import FakeResponse

FIXTURES = files("bapp_connectors.providers.shop.bapp_store") / "fixtures"
TASK_PATH = "tasks/store.CatalogSyncTask"


@pytest.fixture(scope="module")
def batch() -> dict:
    return json.loads((FIXTURES / "products_batch.json").read_text())


@pytest.fixture
def fake():
    return FakeHttpClient()


@pytest.fixture
def adapter(fake):
    return BappStoreShopAdapter(
        credentials={"store_url": "https://demo-st.sites.bapp.ro/", "token": "tok"},
        http_client=fake,
        config={"vat_rate": "0.21"},
    )


def _products(batch) -> list[Product]:
    out = []
    for record in batch["request"]["products"]:
        out.append(Product(
            product_id=record["id"], sku=record["code"], name=record["name"], price=Decimal("1.00"),
            stock=int(record["stock"]), category_ids=record["category_ids"],
            extra={"bapp": record["extra"]["bapp"], "price_tiers": []},
        ))
    return out


def test_class_attributes():
    assert BappStoreShopAdapter.sideloads_images is False
    assert BappStoreShopAdapter.supports_modified_since is False
    assert BappStoreShopAdapter.accepts_local_category_id is True
    assert BappStoreShopAdapter.max_batch_size == 100


def test_validate_credentials(adapter):
    assert adapter.validate_credentials() is True
    assert BappStoreShopAdapter(credentials={"store_url": "https://x"}).validate_credentials() is False


def test_test_connection_success(adapter, fake):
    fake.add("GET", "content-type/store.storecategory/", {"count": 0, "results": []})
    result = adapter.test_connection()
    assert result.success is True


def test_test_connection_reports_non_auth_failures_as_themselves(adapter, fake):
    def server_error(method, path, kwargs):
        raise ProviderError("Company Store server error 503: maintenance", retryable=True, status_code=503)

    fake.add("GET", "content-type/store.storecategory/", server_error)
    result = adapter.test_connection()
    assert result.success is False
    assert result.message != "Authentication failed"
    assert "503" in result.message


def test_bulk_upsert_sends_one_task_and_splits_positional_results(adapter, fake, batch):
    products = _products(batch)
    response = {"categories": [], "products": [
        {"index": 0, "id": "345100", "status": "created", "error": "", "code": ""},
        {"index": 1, "id": "345101", "status": "error", "error": "category 159 unknown", "code": "unknown_category"},
        {"index": 2, "id": "345102", "status": "updated", "error": "", "code": ""},
    ], "rules_applied": False, "webhook_applied": False}
    fake.add("POST", TASK_PATH, FakeResponse(200, response))
    update = ProductUpdate(product_id="345102", stock=5, extra={"bapp": {"gross_price": "60.50"}})
    result = adapter.bulk_upsert_products(products[:2], [update])
    assert len(fake.calls) == 1
    call = fake.last_call()
    assert call.method == "POST" and call.path.endswith(TASK_PATH)
    assert call.kwargs["headers"]["X-App-Slug"] == "sync"
    sent = call.kwargs["json"]["products"]
    assert [r["id"] for r in sent] == ["345100", "345101", "345102"]
    assert sent[2] == {"id": "345102", "stock": "5", "price": {"amount": "60.50", "currency": "RON"}, "extra": {"bapp": {"gross_price": "60.50"}}}
    assert result.created[0].remote_id == "345100" and result.created[0].ok
    assert result.created[1].error_code == "unknown_category"
    assert result.updated[0].index == 0 and result.updated[0].remote_id == "345102"


def test_bulk_upsert_empty_makes_no_call(adapter, fake):
    assert adapter.bulk_upsert_products([], []).created == []
    assert fake.calls == []


def test_bulk_upsert_over_limit_raises(adapter, fake, batch):
    products = _products(batch) * 34  # 102 > 100
    with pytest.raises(ValueError):
        adapter.bulk_upsert_products(products, [])
    assert fake.calls == []


def test_create_product_returns_product_and_raises_on_item_error(adapter, fake, batch):
    product = _products(batch)[0]
    fake.add("POST", TASK_PATH, FakeResponse(200, {"products": [{"index": 0, "id": "345100", "status": "created", "error": "", "code": ""}]}))
    assert adapter.create_product(product).product_id == "345100"
    fake.responses.clear()
    fake.add("POST", TASK_PATH, FakeResponse(200, {"products": [{"index": 0, "id": "345100", "status": "error", "error": "bad price", "code": "invalid_price"}]}))
    with pytest.raises(PermanentProviderError, match="bad price"):
        adapter.create_product(product)


def test_update_product_posts_single_update_record(adapter, fake):
    fake.add("POST", TASK_PATH, FakeResponse(200, {"products": [{"index": 0, "id": "1", "status": "updated", "error": "", "code": ""}]}))
    adapter.update_product(ProductUpdate(product_id="1", name="Nou"))
    assert fake.last_call().kwargs["json"] == {"products": [{"id": "1", "name": "Nou"}]}


def test_find_product_by_sku_matches_exact_code(adapter, fake):
    fake.add("GET", "content-type/store.storeproduct/", {"count": 2, "next": None, "results": [
        {"id": 3, "external_id": "9", "code": "AB-10", "code_ean": "", "name": "Other", "price_amount": "12.1000", "stock_qty": "1"},
        {"id": 4, "external_id": "10", "code": "AB-1", "code_ean": "", "name": "Ciocan", "price_amount": "12.1000", "stock_qty": "1"},
    ]})
    product = adapter.find_product_by_sku("AB-1")
    assert product is not None and product.product_id == "10" and product.price == Decimal("10.00")
    assert fake.last_call().kwargs["params"]["code"] == "AB-1"


def test_find_product_by_sku_blank_short_circuits(adapter, fake):
    assert adapter.find_product_by_sku("") is None
    assert fake.calls == []


def test_get_products_pages_by_cursor(adapter, fake):
    fake.add("GET", "content-type/store.storeproduct/", {"count": 120, "next": "https://x/?page=3&page_size=100", "results": [
        {"id": 4, "external_id": "10", "code": "AB-1", "code_ean": "", "name": "Ciocan", "price_amount": "12.1000", "stock_qty": "1"},
    ]})
    page = adapter.get_products(cursor="2")
    assert fake.last_call().kwargs["params"] == {"page_size": 100, "page": 2}
    assert page.items[0].product_id == "10" and page.has_more is True and page.cursor == "3" and page.total == 120


@pytest.mark.parametrize("call", [
    lambda a: a.update_product_stock("1", 3),
    lambda a: a.update_product_price("1", Decimal("1"), "RON"),
    lambda a: a.update_order_status("1", None),
    lambda a: a.delete_product("1"),
])
def test_unsupported_methods_raise(adapter, call):
    with pytest.raises(UnsupportedFeatureError):
        call(adapter)


@pytest.fixture(scope="module")
def rules_fixture() -> dict:
    return json.loads((FIXTURES / "rules.json").read_text())


def test_get_categories_remaps_bare_parent_pk_to_external_id(adapter, fake):
    fake.add("GET", "content-type/store.storecategory/", {"count": 2, "next": None, "results": [
        {"id": 5, "external_id": "159", "name": "Scule", "parent": None, "is_active": True},
        {"id": 7, "external_id": "160", "name": "Burghie", "parent": 5, "is_active": True},
    ]})
    categories = adapter.get_categories()
    assert [(c.category_id, c.parent_id) for c in categories] == [("159", None), ("160", "159")]


def test_create_category_sends_local_id_record(adapter, fake, batch):
    fake.add("POST", TASK_PATH, FakeResponse(200, {"categories": [{"index": 0, "id": "160", "status": "created", "error": "", "code": ""}]}))
    created = adapter.create_category("Burghie", parent_id="159", local_id="160")
    assert fake.last_call().kwargs["json"] == {"categories": [batch["request"]["categories"][1]]}
    assert created.category_id == "160" and created.parent_id == "159" and created.name == "Burghie"


def test_create_category_without_local_id_is_rejected(adapter, fake):
    with pytest.raises(ValueError):
        adapter.create_category("Scule")
    assert fake.calls == []


def test_create_category_item_error_raises(adapter, fake):
    fake.add("POST", TASK_PATH, FakeResponse(200, {"categories": [{"index": 0, "id": "160", "status": "error", "error": "parent 999 unknown", "code": "unknown_category"}]}))
    with pytest.raises(PermanentProviderError, match="parent 999 unknown"):
        adapter.create_category("Burghie", parent_id="999", local_id="160")


def test_update_category_sends_name_and_parent(adapter, fake):
    fake.add("POST", TASK_PATH, FakeResponse(200, {"categories": [{"index": 0, "id": "160", "status": "updated", "error": "", "code": ""}]}))
    result = adapter.update_category(ProductCategory(category_id="160", name="Burghie HSS", parent_id="159"))
    assert fake.last_call().kwargs["json"] == {"categories": [{"id": "160", "parent_id": "159", "name": "Burghie HSS"}]}
    assert result.category_id == "160"


def test_push_shop_rules_body_matches_fixture(adapter, fake, rules_fixture):
    fake.add("POST", TASK_PATH, FakeResponse(200, rules_fixture["response"]))
    rules = ShopRules(
        order_value_tiers=[
            OrderValueTier(min_total=Decimal("5000.00"), discount_percent=Decimal("3.00")),
            OrderValueTier(min_total=Decimal("10000.00"), discount_percent=Decimal("5.00")),
        ],
        min_order_total=Decimal("1000.00"),
        currency="RON",
        extra={"connection_id": 123, "synced_at": "2026-09-02T12:00:00+03:00"},
    )
    adapter.push_shop_rules(rules)
    assert fake.last_call().kwargs["json"] == rules_fixture["request"]


def test_push_shop_rules_not_applied_raises(adapter, fake):
    fake.add("POST", TASK_PATH, FakeResponse(200, {"rules_applied": False}))
    with pytest.raises(PermanentProviderError):
        adapter.push_shop_rules(ShopRules(currency="RON"))


def test_verify_webhook_hex_hmac_over_body(adapter):
    body = json.dumps({"id": "ORD-000123", "event": "order.created"}).encode()
    good = hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
    assert adapter.verify_webhook({"X-BappStore-Signature": good}, body, secret="s3cret") is True
    assert adapter.verify_webhook({"x-bappstore-signature": good.upper()}, body, secret="s3cret") is True
    assert adapter.verify_webhook({"X-BappStore-Signature": good}, body + b" ", secret="s3cret") is False
    assert adapter.verify_webhook({"X-BappStore-Signature": good}, body, secret="other") is False
    assert adapter.verify_webhook({}, body, secret="s3cret") is False
    assert adapter.verify_webhook({"X-BappStore-Signature": good}, body, secret="") is False
    # hmac.compare_digest raises TypeError on non-ASCII str operands; must fail closed, not raise.
    assert adapter.verify_webhook({"X-BappStore-Signature": "café"}, body, secret="s3cret") is False


def test_parse_webhook_maps_event_and_order_id(adapter):
    body = json.dumps({"id": "ORD-000123", "event": "order.created"}).encode()
    event = adapter.parse_webhook({}, body)
    assert event.event_type is WebhookEventType.ORDER_CREATED
    assert event.provider == "bapp_store" and event.provider_event_type == "order.created"
    assert event.payload == {"id": "ORD-000123"}
    assert event.idempotency_key == "order.created:ORD-000123"


def test_parse_webhook_unknown_event(adapter):
    event = adapter.parse_webhook({}, json.dumps({"id": "1", "event": "order.deleted"}).encode())
    assert event.event_type is WebhookEventType.UNKNOWN
