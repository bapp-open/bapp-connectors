"""Tests for OAuthService — signed-state authorize/exchange/refresh flow."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.core import signing

from bapp_connectors.core.capabilities.oauth import OAuthCapability, OAuthTokens
from bapp_connectors.core.errors import ConfigurationError
from django_bapp_connectors.services.oauth import STATE_SALT, OAuthService
from tests.testapp.models import Connection


class FakeOAuthAdapter(OAuthCapability):
    """Minimal OAuth-capable adapter double recording the calls it receives."""

    def __init__(self, tokens: OAuthTokens | None = None):
        self.tokens = tokens or OAuthTokens(access_token="new-access")
        self.authorize_calls: list[tuple[str, str]] = []
        self.exchange_calls: list[tuple[str, str, str]] = []
        self.refresh_calls: list[str] = []

    def get_authorize_url(self, redirect_uri: str, state: str = "") -> str:
        self.authorize_calls.append((redirect_uri, state))
        return f"https://provider.example/authorize?state={state}"

    def exchange_code_for_token(self, code: str, redirect_uri: str, state: str = "") -> OAuthTokens:
        self.exchange_calls.append((code, redirect_uri, state))
        return self.tokens

    def refresh_token(self, refresh_token: str) -> OAuthTokens:
        self.refresh_calls.append(refresh_token)
        return self.tokens


@pytest.fixture
def connection(db):
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


def _patch_adapter(adapter):
    return patch(
        "django_bapp_connectors.services.connection.ConnectionService.get_adapter",
        return_value=adapter,
    )


# ── get_authorize_url ──


class TestGetAuthorizeUrl:
    def test_returns_adapter_url_with_signed_state(self, connection):
        adapter = FakeOAuthAdapter()
        with _patch_adapter(adapter):
            url = OAuthService.get_authorize_url(connection, "https://app.example/cb/")

        assert url.startswith("https://provider.example/authorize?state=")
        redirect_uri, state = adapter.authorize_calls[0]
        assert redirect_uri == "https://app.example/cb/"

        payload = signing.loads(state, salt=STATE_SALT)
        assert payload == {
            "connection_id": connection.pk,
            "redirect_uri": "https://app.example/cb/",
        }

    def test_raises_for_provider_without_oauth_support(self, connection):
        with _patch_adapter(object()), pytest.raises(ConfigurationError):
            OAuthService.get_authorize_url(connection, "https://app.example/cb/")


# ── complete_authorization ──


class TestCompleteAuthorization:
    def _state_for(self, connection, redirect_uri="https://app.example/cb/"):
        return signing.dumps(
            {"connection_id": connection.pk, "redirect_uri": redirect_uri},
            salt=STATE_SALT,
        )

    def test_exchanges_code_and_stores_provider_credentials(self, connection):
        tokens = OAuthTokens(
            access_token="user-token",
            extra={"credentials": {"token": "user-token", "app_id": "app-1", "app_secret": "s3cret"}},
        )
        adapter = FakeOAuthAdapter(tokens)
        state = self._state_for(connection)

        with _patch_adapter(adapter):
            result = OAuthService.complete_authorization(state=state, code="auth-code")

        assert result.pk == connection.pk
        code, redirect_uri, sent_state = adapter.exchange_calls[0]
        assert code == "auth-code"
        assert redirect_uri == "https://app.example/cb/"
        assert sent_state == state

        connection.refresh_from_db()
        assert connection.credentials == {
            "app_id": "app-1",
            "app_secret": "s3cret",
            "token": "user-token",
        }

    def test_marks_connection_connected(self, connection):
        adapter = FakeOAuthAdapter()
        with _patch_adapter(adapter):
            OAuthService.complete_authorization(state=self._state_for(connection), code="c")

        connection.refresh_from_db()
        assert connection.is_connected is True
        assert connection.auth_failure_count == 0

    def test_falls_back_to_token_fields_when_no_extra_credentials(self, connection):
        tokens = OAuthTokens(access_token="plain-access", refresh_token="plain-refresh")
        adapter = FakeOAuthAdapter(tokens)

        with _patch_adapter(adapter):
            OAuthService.complete_authorization(state=self._state_for(connection), code="c")

        connection.refresh_from_db()
        assert connection.credentials["access_token"] == "plain-access"
        assert connection.credentials["refresh_token"] == "plain-refresh"
        # Pre-existing app credentials survive the merge
        assert connection.credentials["app_id"] == "app-1"

    def test_rejects_tampered_state(self, connection, db):
        forged = signing.dumps({"connection_id": connection.pk}, salt="wrong-salt")
        with pytest.raises(signing.BadSignature):
            OAuthService.complete_authorization(state=forged, code="c")

    def test_rejects_unknown_connection(self, db):
        state = signing.dumps(
            {"connection_id": 999999, "redirect_uri": "https://app.example/cb/"},
            salt=STATE_SALT,
        )
        with pytest.raises(Connection.DoesNotExist):
            OAuthService.complete_authorization(state=state, code="c")


# ── refresh_tokens ──


class TestRefreshTokens:
    def test_uses_stored_refresh_token_and_merges_result(self, connection):
        connection.credentials = {"refresh_token": "old-refresh", "access_token": "old-access"}
        connection.save()
        tokens = OAuthTokens(
            access_token="fresh-access",
            refresh_token="rotated-refresh",
            extra={"credentials": {"access_token": "fresh-access", "refresh_token": "rotated-refresh"}},
        )
        adapter = FakeOAuthAdapter(tokens)

        with _patch_adapter(adapter):
            result = OAuthService.refresh_tokens(connection)

        assert adapter.refresh_calls == ["old-refresh"]
        assert result.access_token == "fresh-access"
        connection.refresh_from_db()
        assert connection.credentials["access_token"] == "fresh-access"
        assert connection.credentials["refresh_token"] == "rotated-refresh"

    def test_falls_back_to_access_token_for_meta_style_refresh(self, connection):
        # Meta has no refresh tokens — its refresh grant takes the current token.
        connection.credentials = {"token": "current-page-token", "app_id": "app-1"}
        connection.save()
        adapter = FakeOAuthAdapter(
            OAuthTokens(access_token="long-lived", extra={"credentials": {"token": "long-lived"}})
        )

        with _patch_adapter(adapter):
            OAuthService.refresh_tokens(connection)

        assert adapter.refresh_calls == ["current-page-token"]
        connection.refresh_from_db()
        assert connection.credentials["token"] == "long-lived"
