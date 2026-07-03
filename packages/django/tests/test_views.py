"""Tests for django_bapp_connectors webhook and OAuth views."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.test import Client

from bapp_connectors.core.capabilities.oauth import OAuthCapability, OAuthTokens

from .testapp.models import Connection


@pytest.fixture
def client():
    return Client()


@pytest.fixture
def connection(db):
    return Connection.objects.create(
        provider_family="shop",
        provider_name="woocommerce",
        display_name="Test Shop",
        is_enabled=True,
        is_connected=True,
    )


@pytest.fixture
def oauth_connection(db):
    conn = Connection.objects.create(
        provider_family="social",
        provider_name="facebook",
        display_name="Test Page",
        is_enabled=True,
        is_connected=False,
    )
    conn.credentials = {"app_id": "app-1", "app_secret": "s3cret"}
    conn.save()
    return conn


class _FakeOAuthAdapter(OAuthCapability):
    def get_authorize_url(self, redirect_uri: str, state: str = "") -> str:
        return f"https://provider.example/authorize?state={state}"

    def exchange_code_for_token(self, code: str, redirect_uri: str, state: str = "") -> OAuthTokens:
        return OAuthTokens(
            access_token="exchanged-token",
            extra={"credentials": {"token": "exchanged-token"}},
        )

    def refresh_token(self, refresh_token: str) -> OAuthTokens:
        return OAuthTokens(access_token="refreshed-token")


# ── webhook_receiver ──
# URL pattern: <int:connection_id>/<str:action>/
# Using ROOT_URLCONF that includes the webhooks urls under a namespace.


@pytest.fixture(autouse=True)
def _use_webhook_urls(settings):
    settings.ROOT_URLCONF = "tests.test_views_urls"


class TestWebhookReceiver:
    def test_returns_200_on_post(self, client, connection):
        url = f"/webhooks/{connection.pk}/order.created/"
        response = client.post(
            url,
            data=b'{"id": 1}',
            content_type="application/json",
        )
        assert response.status_code == 200

    def test_returns_403_on_get_without_verify_challenge(self, client, connection):
        # GET is reserved for webhook verification challenges (e.g. Meta's
        # hub.verify_token flow); without a valid challenge it is rejected.
        url = f"/webhooks/{connection.pk}/order.created/"
        response = client.get(url)
        assert response.status_code == 403

    def test_returns_405_on_other_methods(self, client, connection):
        url = f"/webhooks/{connection.pk}/order.created/"
        response = client.put(url, data=b"{}", content_type="application/json")
        assert response.status_code == 405

    def test_returns_200_even_when_connection_does_not_exist(self, client, db):
        url = "/webhooks/99999/order.created/"
        response = client.post(
            url,
            data=b'{"id": 1}',
            content_type="application/json",
        )
        assert response.status_code == 200

    def test_always_returns_json_with_status_received(self, client, connection):
        url = f"/webhooks/{connection.pk}/order.created/"
        response = client.post(
            url,
            data=b'{"test": true}',
            content_type="application/json",
        )
        data = response.json()
        assert data["status"] == "received"
        assert data["connection_id"] == connection.pk
        assert data["action"] == "order.created"


# ── oauth_callback ──
# URL pattern: oauth/callback/<str:provider>/


class TestOAuthCallback:
    def test_returns_400_when_code_param_missing(self, client):
        url = "/webhooks/oauth/callback/woocommerce/"
        response = client.get(url)
        assert response.status_code == 400

        data = response.json()
        assert "error" in data
        assert "Missing authorization code" in data["error"]

    def test_returns_200_ok_when_code_present_without_state(self, client):
        # No state → flow was not started via OAuthService; acknowledge only.
        url = "/webhooks/oauth/callback/woocommerce/?code=abc123"
        response = client.get(url)
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "ok"
        assert data["provider"] == "woocommerce"

    def test_returns_400_when_provider_reports_error(self, client):
        url = "/webhooks/oauth/callback/facebook/?error=access_denied"
        response = client.get(url)
        assert response.status_code == 400
        assert "access_denied" in response.json()["error"]

    def test_returns_400_for_invalid_state(self, client, db):
        url = "/webhooks/oauth/callback/facebook/?code=abc123&state=tampered"
        response = client.get(url)
        assert response.status_code == 400
        assert "state" in response.json()["error"].lower()

    def test_completes_authorization_with_valid_state(self, client, oauth_connection):
        from django.core import signing

        from django_bapp_connectors.services.oauth import STATE_SALT

        state = signing.dumps(
            {"connection_id": oauth_connection.pk, "redirect_uri": "https://app.example/cb/"},
            salt=STATE_SALT,
        )
        adapter = _FakeOAuthAdapter()
        with patch(
            "django_bapp_connectors.services.connection.ConnectionService.get_adapter",
            return_value=adapter,
        ):
            response = client.get(f"/webhooks/oauth/callback/facebook/?code=abc123&state={state}")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "connected"
        assert data["connection_id"] == oauth_connection.pk

        oauth_connection.refresh_from_db()
        assert oauth_connection.is_connected is True
        assert oauth_connection.credentials["token"] == "exchanged-token"

    def test_redirects_to_success_url_when_configured(self, client, oauth_connection, settings):
        from django.core import signing

        from django_bapp_connectors.services.oauth import STATE_SALT

        settings.BAPP_CONNECTORS = {
            **settings.BAPP_CONNECTORS,
            "OAUTH_SUCCESS_REDIRECT": "/settings/connections/",
        }
        state = signing.dumps(
            {"connection_id": oauth_connection.pk, "redirect_uri": "https://app.example/cb/"},
            salt=STATE_SALT,
        )
        with patch(
            "django_bapp_connectors.services.connection.ConnectionService.get_adapter",
            return_value=_FakeOAuthAdapter(),
        ):
            response = client.get(f"/webhooks/oauth/callback/facebook/?code=abc123&state={state}")

        assert response.status_code == 302
        assert response["Location"] == f"/settings/connections/?connection_id={oauth_connection.pk}"

    def test_redirects_to_error_url_when_configured(self, client, db, settings):
        settings.BAPP_CONNECTORS = {
            **settings.BAPP_CONNECTORS,
            "OAUTH_ERROR_REDIRECT": "/settings/connections/error/",
        }
        response = client.get("/webhooks/oauth/callback/facebook/?error=access_denied")

        assert response.status_code == 302
        assert response["Location"].startswith("/settings/connections/error/?error=")

    def test_returns_400_for_unknown_connection_id(self, client, db):
        from django.core import signing

        from django_bapp_connectors.services.oauth import STATE_SALT

        state = signing.dumps(
            {"connection_id": 999999, "redirect_uri": "https://app.example/cb/"},
            salt=STATE_SALT,
        )
        response = client.get(f"/webhooks/oauth/callback/facebook/?code=abc123&state={state}")
        assert response.status_code == 400
