from bapp_connectors.core.capabilities import (
    CustomerDetailsCapability,
    FulfillmentCapability,
    OrderAmountCapability,
    ProductCreationCapability,
    ReturnsCapability,
    WebhookCapability,
)
from bapp_connectors.core.registry import registry
from bapp_connectors.providers.shop.temu.adapter import REQUIRED_SCOPES, TemuShopAdapter
from bapp_connectors.providers.shop.temu.manifest import manifest
from tests.shop.temu.conftest import CREDS, ok


def _route(token_result, settle_result):
    def route(method, path, kwargs):
        t = kwargs["json"]["type"]
        if t == "bg.open.accesstoken.info.get":
            return ok(token_result)
        if t == "temu.local.mall.settlestatus.get":
            return ok(settle_result)
        raise AssertionError(t)

    return route


def test_registered_with_capabilities():
    import bapp_connectors.providers.shop.temu  # noqa: F401

    assert registry.is_registered("shop", "temu")
    for cap in (
        FulfillmentCapability,
        OrderAmountCapability,
        CustomerDetailsCapability,
        ReturnsCapability,
        WebhookCapability,
        ProductCreationCapability,
    ):
        assert cap in manifest.capabilities
    assert manifest.webhooks.supported and manifest.webhooks.signature_method == "temu-hmac-aes"
    names = [f.name for f in manifest.auth.required_fields]
    assert names == ["app_key", "app_secret", "access_token", "region", "mall_id"]
    mall = next(f for f in manifest.auth.required_fields if f.name == "mall_id")
    assert mall.role == "endpoint" and mall.required is False


def test_registry_builds_adapter_that_signs_and_targets_router(fake):
    # the registry injects a NoAuth client for the placeholder base_url: the adapter must still work
    adapter = TemuShopAdapter(CREDS, http_client=fake, config={})
    fake.add("POST", "openapi/router", _route(
        {"mallId": 42, "apiScopeList": list(REQUIRED_SCOPES), "expiredTime": 1824222274},
        {"mallId": 42, "mallName": "Shop", "settleStatus": 99},
    ))
    res = adapter.test_connection()
    assert res.success and res.details["detected_credentials"] == {"mall_id": "42"}
    assert res.details["missing_scopes"] == [] and "Shop" in res.message and "2027-10-22" in res.message
    assert fake.last_call().path.startswith("https://openapi-b-eu.temu.com/") and "sign" in fake.last_call().kwargs["json"]


def test_test_connection_reports_missing_scopes(fake):
    adapter = TemuShopAdapter(CREDS, http_client=fake, config={})
    fake.add("POST", "openapi/router", _route(
        {"mallId": 42, "apiScopeList": [], "expiredTime": 1824222274},
        {"mallId": 42, "mallName": "Shop", "settleStatus": 99},
    ))
    res = adapter.test_connection()
    assert res.success and "temu.order.amount.v2.query" in res.details["missing_scopes"] and "lipsesc" in res.message


def test_test_connection_failure_is_reported_not_raised(fake):
    adapter = TemuShopAdapter(CREDS, http_client=fake, config={})
    fake.add("POST", "openapi/router", {"success": False, "errorCode": 3000030, "errorMsg": "no token", "requestId": "r"})
    res = adapter.test_connection()
    assert res.success is False and "no token" in res.message


def test_detect_credentials_returns_mall_id(fake):
    adapter = TemuShopAdapter(CREDS, http_client=fake, config={})
    fake.add("POST", "openapi/router", ok({"mallId": 42, "apiScopeList": [], "expiredTime": 1}))
    assert adapter.detect_credentials() == {"mall_id": "42"}


def test_default_warehouse_id_prefers_config_then_flagged(fake):
    adapter = TemuShopAdapter(CREDS, http_client=fake, config={"warehouse_id": "WH-CFG"})
    assert adapter.default_warehouse_id() == "WH-CFG"
    adapter = TemuShopAdapter(CREDS, http_client=fake, config={})
    fake.add("POST", "openapi/router", ok({"warehouseList": [
        {"warehouseId": "WH-A", "defaultWarehouse": False}, {"warehouseId": "WH-B", "defaultWarehouse": True}]}))
    assert adapter.default_warehouse_id() == "WH-B"


def test_manifest_settings_defaults():
    defaults = {f.name: f.default for f in manifest.settings.fields}
    assert defaults["fulfillment"] == "self" and defaults["invoice_upload"] == "nightly"
    assert defaults["weight_unit"] == "g" and defaults["size_unit"] == "cm"
    assert defaults["import_orders_without_amounts"] is False and defaults["default_weight_g"] == 100


def test_validate_credentials_requires_the_three_secrets():
    assert TemuShopAdapter(CREDS, http_client=None, config={}).validate_credentials()
    assert not TemuShopAdapter({"app_key": "k"}, http_client=None, config={}).validate_credentials()
