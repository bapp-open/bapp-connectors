"""Tests for SettingsField, SettingsConfig, and settings flow through the registry."""

import pytest

from bapp_connectors.core.dto import ConnectionTestResult
from bapp_connectors.core.errors import ConfigurationError
from bapp_connectors.core.manifest import (
    AuthConfig,
    CredentialField,
    ProviderManifest,
    SettingsConfig,
    SettingsField,
)
from bapp_connectors.core.ports import ShopPort
from bapp_connectors.core.registry import ProviderRegistry
from bapp_connectors.core.types import AuthStrategy, FieldType, ProviderFamily


# ── SettingsField tests ──


def test_settings_field_auto_label():
    f = SettingsField(name="printer_type")
    assert f.label == "Printer Type"


def test_settings_field_explicit_label():
    f = SettingsField(name="printer_type", label="AWB Format")
    assert f.label == "AWB Format"


def test_settings_field_defaults():
    f = SettingsField(name="mode")
    assert f.field_type == FieldType.STR
    assert f.required is False
    assert f.default is None
    assert f.choices is None


# ── SettingsConfig tests ──


def test_validate_settings_required_missing():
    config = SettingsConfig(fields=[
        SettingsField(name="mode", field_type=FieldType.SELECT, choices=["live", "test"], required=True),
    ])
    errors = config.validate_settings({})
    assert len(errors) == 1
    assert "Missing required setting: mode" in errors[0]


def test_validate_settings_required_present():
    config = SettingsConfig(fields=[
        SettingsField(name="mode", field_type=FieldType.SELECT, choices=["live", "test"], required=True),
    ])
    errors = config.validate_settings({"mode": "live"})
    assert errors == []


def test_validate_settings_invalid_choice():
    config = SettingsConfig(fields=[
        SettingsField(name="mode", field_type=FieldType.SELECT, choices=["live", "test"]),
    ])
    errors = config.validate_settings({"mode": "invalid"})
    assert len(errors) == 1
    assert "Invalid value for mode" in errors[0]


def test_validate_settings_valid_choice():
    config = SettingsConfig(fields=[
        SettingsField(name="mode", field_type=FieldType.SELECT, choices=["live", "test"]),
    ])
    errors = config.validate_settings({"mode": "test"})
    assert errors == []


def test_validate_settings_no_fields():
    config = SettingsConfig()
    errors = config.validate_settings({"anything": "goes"})
    assert errors == []


def test_apply_defaults_fills_missing():
    config = SettingsConfig(fields=[
        SettingsField(name="page_size", field_type=FieldType.INT, default=50),
        SettingsField(name="mode", field_type=FieldType.SELECT, default="live"),
    ])
    result = config.apply_defaults({})
    assert result == {"page_size": 50, "mode": "live"}


def test_apply_defaults_preserves_existing():
    config = SettingsConfig(fields=[
        SettingsField(name="page_size", field_type=FieldType.INT, default=50),
    ])
    result = config.apply_defaults({"page_size": 100})
    assert result == {"page_size": 100}


def test_apply_defaults_skips_none_default():
    config = SettingsConfig(fields=[
        SettingsField(name="optional_field", field_type=FieldType.STR),
    ])
    result = config.apply_defaults({})
    assert "optional_field" not in result


def test_apply_defaults_preserves_extra_keys():
    config = SettingsConfig(fields=[
        SettingsField(name="page_size", field_type=FieldType.INT, default=50),
    ])
    result = config.apply_defaults({"page_size": 100, "custom_key": "value"})
    assert result == {"page_size": 100, "custom_key": "value"}


# ── Registry integration tests ──


class _DummyWithSettings(ShopPort):
    manifest = ProviderManifest(
        name="dummy_settings",
        family=ProviderFamily.SHOP,
        base_url="https://api.dummy.com/",
        auth=AuthConfig(
            strategy=AuthStrategy.TOKEN,
            required_fields=[CredentialField(name="token")],
        ),
        settings=SettingsConfig(
            fields=[
                SettingsField(name="page_size", field_type=FieldType.INT, default=50),
                SettingsField(name="mode", field_type=FieldType.SELECT, choices=["live", "test"], required=True),
            ],
        ),
        capabilities=[ShopPort],
    )

    def __init__(self, credentials, http_client=None, config=None, **kwargs):
        self.credentials = credentials
        self.config = config or {}

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

    def update_order_status(self, order_id, status):
        pass


def test_registry_passes_config_with_defaults():
    reg = ProviderRegistry()
    reg.register(_DummyWithSettings)
    adapter = reg.create_adapter(
        "shop", "dummy_settings",
        credentials={"token": "abc"},
        config={"mode": "live"},
    )
    assert adapter.config["page_size"] == 50  # default applied
    assert adapter.config["mode"] == "live"   # user value preserved


def test_registry_rejects_missing_required_setting():
    reg = ProviderRegistry()
    reg.register(_DummyWithSettings)
    with pytest.raises(ConfigurationError, match="Missing required setting: mode"):
        reg.create_adapter(
            "shop", "dummy_settings",
            credentials={"token": "abc"},
            config={},
        )


def test_registry_rejects_invalid_choice():
    reg = ProviderRegistry()
    reg.register(_DummyWithSettings)
    with pytest.raises(ConfigurationError, match="Invalid value for mode"):
        reg.create_adapter(
            "shop", "dummy_settings",
            credentials={"token": "abc"},
            config={"mode": "invalid"},
        )


def test_registry_no_settings_backward_compat():
    """Adapters without declared settings work fine with or without config."""

    class _NoSettings(ShopPort):
        manifest = ProviderManifest(
            name="no_settings",
            family=ProviderFamily.SHOP,
            base_url="https://api.dummy.com/",
            auth=AuthConfig(
                strategy=AuthStrategy.TOKEN,
                required_fields=[CredentialField(name="token")],
            ),
            capabilities=[ShopPort],
        )

        def __init__(self, credentials, http_client=None, config=None, **kwargs):
            self.credentials = credentials
            self.config = config or {}

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

        def update_order_status(self, order_id, status):
            pass

    reg = ProviderRegistry()
    reg.register(_NoSettings)

    # Without config
    adapter = reg.create_adapter("shop", "no_settings", credentials={"token": "abc"})
    assert adapter.config == {}

    # With arbitrary config (no validation since no fields declared)
    adapter = reg.create_adapter("shop", "no_settings", credentials={"token": "abc"}, config={"anything": True})
    assert adapter.config == {"anything": True}
