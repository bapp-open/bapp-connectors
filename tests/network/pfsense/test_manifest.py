from bapp_connectors.core.ports import NetworkPort
from bapp_connectors.core.types import AuthStrategy, FieldType, ProviderFamily
from bapp_connectors.providers.network.pfsense.manifest import manifest


def test_identity():
    assert manifest.name == "pfsense"
    assert manifest.family == ProviderFamily.NETWORK
    assert manifest.display_name == "pfSense"
    assert manifest.allow_multiple is True
    assert manifest.validate() == []


def test_auth_and_settings():
    assert manifest.auth.strategy == AuthStrategy.BASIC
    names = [f.name for f in manifest.auth.required_fields]
    assert names == ["username", "password"]
    assert next(f for f in manifest.auth.required_fields if f.name == "password").sensitive is True
    settings = {f.name: f for f in manifest.settings.fields}
    assert settings["endpoints"].field_type == FieldType.TEXTAREA and settings["endpoints"].required is True
    assert settings["verify_ssl"].field_type == FieldType.BOOL and settings["verify_ssl"].default is False
    assert settings["timeout"].field_type == FieldType.INT and settings["timeout"].default == 20
    assert NetworkPort in manifest.capabilities
    assert manifest.webhooks.supported is False


def test_registered_in_registry():
    import bapp_connectors.providers.network.pfsense  # noqa: F401
    from bapp_connectors.core.registry import registry

    assert registry.get_adapter_class("network", "pfsense").manifest is manifest
