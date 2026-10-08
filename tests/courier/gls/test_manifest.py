"""Credentials and settings declared by the GLS connector."""

from __future__ import annotations

from bapp_connectors.core.capabilities import BatchTrackingCapability
from bapp_connectors.core.types import FieldType
from bapp_connectors.providers.courier.gls.manifest import manifest


def _setting(name: str):
    return next((f for f in manifest.settings.fields if f.name == name), None)


def _credential(name: str):
    return next((f for f in manifest.auth.required_fields if f.name == name), None)


def test_test_environment_is_an_optional_credential():
    field = _credential("test")
    assert field is not None and field.required is False and field.default == "false"
    assert manifest.auth.validate_credentials(
        {"username": "u", "password": "p", "client_number": "1", "country": "RO"}) == []


def test_notification_services_are_settings():
    for name in ("service_sm1", "service_sm2", "service_fds", "service_fss", "hide_phone_on_label"):
        field = _setting(name)
        assert field is not None and field.field_type == FieldType.BOOL and field.default is False
    assert _setting("service_sm1_text").field_type == FieldType.TEXTAREA


def test_printer_types_from_the_documentation():
    assert {"ThermoZPL", "ThermoZPL_300DPI", "ShipItThermoPdf"} <= set(_setting("printer_type").choices)
    assert _setting("printer_type").default == "Connect"


def test_batch_tracking_is_declared():
    assert BatchTrackingCapability in manifest.capabilities
