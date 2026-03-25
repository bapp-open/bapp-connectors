"""
WooCommerce OAuth unit tests — no Docker required.

Tests the OAuthCapability implementation for the WooCommerce pseudo-OAuth flow.
"""

from __future__ import annotations

import json

import pytest

from bapp_connectors.core.capabilities import OAuthCapability
from bapp_connectors.core.capabilities.oauth import OAuthTokens
from bapp_connectors.providers.shop.woocommerce.adapter import WooCommerceShopAdapter
from bapp_connectors.providers.shop.woocommerce.manifest import manifest


class TestWooCommerceOAuth:

    def test_oauth_capability_declared_in_manifest(self):
        assert OAuthCapability in manifest.capabilities
        assert manifest.auth.oauth is not None
        assert manifest.auth.oauth.display_name == "Connect with WooCommerce"
        assert len(manifest.auth.oauth.credential_fields) == 1  # just domain
        assert manifest.auth.oauth.scopes == ["read_write"]

    def test_get_authorize_url(self):
        adapter = WooCommerceShopAdapter(credentials={
            "domain": "https://myshop.com",
        })
        url = adapter.get_authorize_url("https://example.com/callback", state="user123")
        assert "myshop.com/wc-auth/v1/authorize" in url
        assert "app_name=BApp" in url
        assert "scope=read_write" in url
        assert "return_url=" in url
        assert "callback_url=" in url
        assert "user_id=user123" in url

    def test_exchange_code_for_token(self):
        adapter = WooCommerceShopAdapter(credentials={
            "domain": "https://myshop.com",
        })
        # WooCommerce POSTs credentials directly — the "code" is the JSON body
        wc_callback_body = json.dumps({
            "consumer_key": "ck_abc123",
            "consumer_secret": "cs_xyz789",
            "key_permissions": "read_write",
        })
        tokens = adapter.exchange_code_for_token(wc_callback_body, "https://example.com/callback")
        assert isinstance(tokens, OAuthTokens)
        assert tokens.access_token == "ck_abc123"
        assert tokens.extra["credentials"]["consumer_key"] == "ck_abc123"
        assert tokens.extra["credentials"]["consumer_secret"] == "cs_xyz789"
        assert tokens.extra["credentials"]["domain"] == "https://myshop.com"
        assert tokens.extra["key_permissions"] == "read_write"

    def test_refresh_token_raises(self):
        adapter = WooCommerceShopAdapter(credentials={"domain": "https://myshop.com"})
        with pytest.raises(NotImplementedError):
            adapter.refresh_token("some_token")

    def test_consumer_key_and_secret_not_required(self):
        """After making consumer_key/secret optional, adapter can be created without them."""
        adapter = WooCommerceShopAdapter(credentials={
            "domain": "https://myshop.com",
        })
        assert adapter.domain == "https://myshop.com"
