"""Tests for ConnectionService methods."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from django_bapp_connectors.services.connection import ConnectionService

from tests.testapp.models import Connection


@pytest.fixture
def connection(db):
    return Connection.objects.create(
        provider_family="shop",
        provider_name="woocommerce",
        display_name="Test Shop",
        is_enabled=True,
        is_connected=True,
        config={"webhook_secret": "abc"},
    )


# ── get_adapter ──


class TestGetAdapter:
    @patch("django_bapp_connectors.services.connection.registry")
    def test_calls_create_adapter_with_correct_args(self, mock_registry, connection):
        mock_adapter = MagicMock()
        mock_registry.create_adapter.return_value = mock_adapter

        result = ConnectionService.get_adapter(connection)

        mock_registry.create_adapter.assert_called_once_with(
            family="shop",
            provider="woocommerce",
            credentials=connection.credentials,
            config=connection.config,
        )
        assert result is mock_adapter


# ── test_connection ──


class TestTestConnection:
    @patch("django_bapp_connectors.services.connection.registry")
    def test_updates_is_connected_true_on_success(self, mock_registry, connection):
        mock_adapter = MagicMock()
        mock_result = MagicMock(success=True, message="OK")
        mock_adapter.test_connection.return_value = mock_result
        mock_registry.create_adapter.return_value = mock_adapter

        result = ConnectionService.test_connection(connection)

        connection.refresh_from_db()
        assert connection.is_connected is True
        assert result is mock_result

    @patch("django_bapp_connectors.services.connection.registry")
    def test_updates_is_connected_false_on_failure(self, mock_registry, connection):
        mock_adapter = MagicMock()
        mock_result = MagicMock(success=False, message="Auth failed")
        mock_adapter.test_connection.return_value = mock_result
        mock_registry.create_adapter.return_value = mock_adapter

        result = ConnectionService.test_connection(connection)

        connection.refresh_from_db()
        assert connection.is_connected is False
        assert result is mock_result


# ── rotate_credentials ──


class TestRotateCredentials:
    def test_updates_credentials_encrypted_field(self, connection):
        new_creds = {"api_key": "new-secret-key"}

        ConnectionService.rotate_credentials(connection, new_creds)

        connection.refresh_from_db()
        assert connection.credentials_encrypted != ""
        assert connection.credentials == new_creds


# ── validate_settings ──


class TestValidateSettings:
    @patch("django_bapp_connectors.services.connection.registry")
    def test_delegates_to_manifest_settings(self, mock_registry, connection):
        mock_manifest = MagicMock()
        mock_manifest.settings.validate_settings.return_value = []
        mock_registry.get_manifest.return_value = mock_manifest

        errors = ConnectionService.validate_settings(connection, {"key": "value"})

        mock_registry.get_manifest.assert_called_once_with("shop", "woocommerce")
        mock_manifest.settings.validate_settings.assert_called_once_with({"key": "value"})
        assert errors == []


# ── update_settings ──


class TestUpdateSettings:
    @patch("django_bapp_connectors.services.connection.registry")
    def test_persists_config_on_valid_settings(self, mock_registry, connection):
        mock_manifest = MagicMock()
        mock_manifest.settings.validate_settings.return_value = []
        mock_registry.get_manifest.return_value = mock_manifest

        new_config = {"sync_interval": 300}
        ConnectionService.update_settings(connection, new_config)

        connection.refresh_from_db()
        assert connection.config == new_config

    @patch("django_bapp_connectors.services.connection.registry")
    def test_raises_configuration_error_on_invalid_settings(self, mock_registry, connection):
        from bapp_connectors.core.errors import ConfigurationError

        mock_manifest = MagicMock()
        mock_manifest.settings.validate_settings.return_value = ["field_x is required"]
        mock_registry.get_manifest.return_value = mock_manifest

        with pytest.raises(ConfigurationError, match="Invalid settings"):
            ConnectionService.update_settings(connection, {"bad": "config"})

        # Config should NOT have been updated
        connection.refresh_from_db()
        assert connection.config == {"webhook_secret": "abc"}


# ── list_available_providers ──


class TestListAvailableProviders:
    @patch("django_bapp_connectors.services.connection.registry")
    def test_delegates_to_registry(self, mock_registry):
        mock_manifests = [MagicMock(), MagicMock()]
        mock_registry.list_providers.return_value = mock_manifests

        result = ConnectionService.list_available_providers()

        mock_registry.list_providers.assert_called_once_with(family=None)
        assert result == mock_manifests

    @patch("django_bapp_connectors.services.connection.registry")
    def test_with_family_filter(self, mock_registry):
        mock_manifests = [MagicMock()]
        mock_registry.list_providers.return_value = mock_manifests

        result = ConnectionService.list_available_providers(family="courier")

        mock_registry.list_providers.assert_called_once_with(family="courier")
        assert result == mock_manifests
