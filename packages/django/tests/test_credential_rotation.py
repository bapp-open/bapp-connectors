"""Generic credential-rotation hook (manifest ``auth.rotating_credentials``) + header redaction."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest
import responses

from bapp_connectors.core.types import ProviderFamily
from django_bapp_connectors.callbacks import _redact
from django_bapp_connectors.services import connection as connection_module
from django_bapp_connectors.services.connection import FAMILY_DEFAULTS, ConnectionService, ensure_providers_loaded
from tests.testapp.models import Connection

SAGA_CREDENTIALS = {"base_url": "https://saga.example.ro", "cod_fiscal": "12345678", "token": "K1"}


@pytest.fixture
def capture_create_adapter(monkeypatch):
    ensure_providers_loaded()
    captured: dict = {}

    def fake_create_adapter(**kwargs):
        captured.update(kwargs)
        return MagicMock()

    monkeypatch.setattr(connection_module.registry, "create_adapter", fake_create_adapter)
    return captured


def test_get_adapter_persists_rotated_token(db, capture_create_adapter):
    conn = Connection.objects.create(
        provider_family="accounting",
        provider_name="saga_web",
        display_name="SAGA",
        config={"keep": "me"},
    )
    conn.credentials = SAGA_CREDENTIALS
    conn.save()

    ConnectionService.get_adapter(conn, log_execution=False)

    callback = capture_create_adapter["on_credentials_update"]
    callback({"token": "K2"})

    conn = Connection.objects.get(pk=conn.pk)
    assert conn.credentials == {**SAGA_CREDENTIALS, "token": "K2"}
    assert conn.config["keep"] == "me"
    datetime.fromisoformat(conn.config["credentials_rotated_at"])


def test_get_adapter_without_flag_passes_no_callback(db, capture_create_adapter):
    conn = Connection.objects.create(provider_family="shop", provider_name="woocommerce", display_name="Shop")

    ConnectionService.get_adapter(conn, log_execution=False)

    assert "on_credentials_update" not in capture_create_adapter


def test_refresh_header_is_redacted():
    redacted = _redact({"X-Saga-Refresh-Token": "K2", "Content-Type": "text/plain"})
    assert redacted == {"X-Saga-Refresh-Token": "***", "Content-Type": "text/plain"}


def test_accounting_family_label():
    assert FAMILY_DEFAULTS[ProviderFamily.ACCOUNTING]["icon"] == "fad fa-calculator"
    assert str(FAMILY_DEFAULTS[ProviderFamily.ACCOUNTING]["label"]) == "Accounting"


@responses.activate
def test_real_saga_web_adapter_persists_rotated_token(db):
    """The real adapter built by ``get_adapter`` (no mock) saves the key SAGA rotates."""
    ensure_providers_loaded()
    base_url = "https://web2.sagasoft.ro/sagac/api/v20260225/"
    responses.add(
        responses.GET,
        base_url + "Situatii/GetSoldCont",
        json={"success": True, "message": "", "data": "100.00"},
        status=200,
        headers={"X-Saga-Refresh-Token": "ROTATED-K2"},
    )
    conn = Connection.objects.create(
        provider_family="accounting", provider_name="saga_web", display_name="SAGA", config={"keep": "me"}
    )
    conn.credentials = {"base_url": base_url, "cod_fiscal": "6716875", "token": "OLD-K1"}
    conn.save()

    adapter = ConnectionService.get_adapter(conn)
    result = adapter.test_connection()

    assert result.success is True
    assert responses.calls[0].request.headers["Authorization"] == "Bearer OLD-K1"
    conn = Connection.objects.get(pk=conn.pk)
    assert conn.credentials["token"] == "ROTATED-K2"
    assert conn.config["keep"] == "me"
    datetime.fromisoformat(conn.config["credentials_rotated_at"])
