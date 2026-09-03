from bapp_connectors.core.capabilities import (
    BulkUpsertCapability,
    CategoryManagementCapability,
    ProductCreationCapability,
    ProductFullUpdateCapability,
    ProductLookupCapability,
    WebhookCapability,
)
from bapp_connectors.core.capabilities.volume_pricing import VolumePricingCapability
from bapp_connectors.core.ports import ShopPort
from bapp_connectors.core.types import AuthStrategy, ProviderFamily
from bapp_connectors.providers.shop.bapp_store.manifest import manifest


def test_identity():
    assert manifest.name == "bapp_store"
    assert manifest.family == ProviderFamily.SHOP
    assert manifest.display_name == "Company Store (BAPP)"
    assert manifest.allow_multiple is True
    assert manifest.validate() == []


def test_credentials():
    assert manifest.auth.strategy == AuthStrategy.CUSTOM
    fields = {f.name: f for f in manifest.auth.required_fields}
    assert fields["store_url"].role == "endpoint" and fields["store_url"].sensitive is False
    assert fields["token"].sensitive is True
    assert manifest.auth.validate_credentials({}) == ["store_url", "token"]
    assert manifest.auth.validate_credentials({"store_url": "https://x-st.sites.bapp.ro", "token": "t"}) == []


def test_settings_have_store_defaults():
    defaults = manifest.settings.apply_defaults({})
    assert defaults["prices_include_vat"] is True
    assert defaults["vat_rate"] == "0.21"
    assert defaults["batch_size"] == 100
    assert defaults["pause_seconds"] == 1
    assert defaults["publish_status"] == "publish"
    assert defaults["sync_images"] is True


def test_publish_status_choices_are_validated():
    assert manifest.settings.validate_settings({"publish_status": "pending"}) != []
    assert manifest.settings.validate_settings({"publish_status": "draft"}) == []


def test_capabilities():
    assert set(manifest.capabilities) == {
        ShopPort,
        BulkUpsertCapability,
        ProductCreationCapability,
        ProductFullUpdateCapability,
        ProductLookupCapability,
        CategoryManagementCapability,
        VolumePricingCapability,
        WebhookCapability,
    }


def test_webhooks_and_limits():
    assert manifest.webhooks.supported is True
    assert manifest.webhooks.signature_method == "hmac-sha256"
    assert manifest.webhooks.signature_header == "X-BappStore-Signature"
    assert manifest.webhooks.events == ["order.created", "order.updated"]
    assert manifest.rate_limit.requests_per_second == 10
    assert manifest.retry.max_retries == 3


def test_package_import_registers_the_adapter():
    import bapp_connectors.providers.shop.bapp_store  # noqa: F401
    from bapp_connectors.core.registry import registry
    from bapp_connectors.providers.shop.bapp_store.adapter import BappStoreShopAdapter

    assert registry.get_adapter_class("shop", "bapp_store") is BappStoreShopAdapter
    assert registry.get_manifest("shop", "bapp_store") is manifest
