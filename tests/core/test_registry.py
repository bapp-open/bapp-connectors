"""Tests for the provider registry."""

import pytest

from bapp_connectors.core.dto import ConnectionTestResult
from bapp_connectors.core.errors import ConfigurationError
from bapp_connectors.core.manifest import (
    AuthConfig,
    CredentialField,
    ProviderManifest,
)
from bapp_connectors.core.ports import ShopPort
from bapp_connectors.core.registry import ProviderRegistry
from bapp_connectors.core.types import AuthStrategy, ProviderFamily


class _DummyShopAdapter(ShopPort):
    manifest = ProviderManifest(
        name="dummy",
        family=ProviderFamily.SHOP,
        base_url="https://api.dummy.com/",
        auth=AuthConfig(
            strategy=AuthStrategy.TOKEN,
            required_fields=[CredentialField(name="token")],
        ),
        capabilities=[ShopPort],
    )

    def __init__(self, credentials, http_client=None, **kwargs):
        self.credentials = credentials

    def validate_credentials(self):
        return True

    def test_connection(self):
        return ConnectionTestResult(success=True)

    def get_orders(self, since=None, cursor=None):
        return []

    def get_order(self, order_id):
        return {}

    def get_products(self, cursor=None):
        return []

    def update_product_stock(self, product_id, quantity):
        pass

    def update_product_price(self, product_id, price, currency):
        pass


def test_register_and_retrieve():
    reg = ProviderRegistry()
    reg.register(_DummyShopAdapter)
    assert reg.is_registered("shop", "dummy")
    cls = reg.get_adapter_class("shop", "dummy")
    assert cls is _DummyShopAdapter


def test_register_no_manifest():
    reg = ProviderRegistry()

    class BadAdapter:
        pass

    with pytest.raises(ConfigurationError, match="no manifest"):
        reg.register(BadAdapter)


def test_register_invalid_manifest():
    reg = ProviderRegistry()

    class BadAdapter:
        manifest = ProviderManifest(name="", family=ProviderFamily.SHOP, base_url="")

    with pytest.raises(ConfigurationError, match="Invalid manifest"):
        reg.register(BadAdapter)


def test_get_unregistered():
    reg = ProviderRegistry()
    with pytest.raises(ConfigurationError, match="No adapter"):
        reg.get_adapter_class("shop", "nonexistent")


def test_list_providers():
    reg = ProviderRegistry()
    reg.register(_DummyShopAdapter)
    manifests = reg.list_providers()
    assert len(manifests) == 1
    assert manifests[0].name == "dummy"


def test_list_providers_filtered():
    reg = ProviderRegistry()
    reg.register(_DummyShopAdapter)
    assert len(reg.list_providers(family="shop")) == 1
    assert len(reg.list_providers(family="courier")) == 0


def test_create_adapter():
    reg = ProviderRegistry()
    reg.register(_DummyShopAdapter)
    adapter = reg.create_adapter("shop", "dummy", credentials={"token": "abc123"})
    assert isinstance(adapter, _DummyShopAdapter)


def test_create_adapter_missing_credentials():
    reg = ProviderRegistry()
    reg.register(_DummyShopAdapter)
    with pytest.raises(ConfigurationError, match="Missing credential"):
        reg.create_adapter("shop", "dummy", credentials={})
