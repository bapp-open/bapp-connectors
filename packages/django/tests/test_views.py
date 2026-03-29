"""Tests for django_bapp_connectors webhook and OAuth views."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from django.test import Client, override_settings

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

    def test_returns_405_on_get(self, client, connection):
        url = f"/webhooks/{connection.pk}/order.created/"
        response = client.get(url)
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

    def test_returns_200_with_provider_when_code_present(self, client):
        url = "/webhooks/oauth/callback/woocommerce/?code=abc123&state=xyz"
        response = client.get(url)
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "ok"
        assert data["provider"] == "woocommerce"
