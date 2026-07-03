"""
OAuth connection flow — authorize, callback exchange, and token refresh.

Works with any provider whose adapter implements ``OAuthCapability``
(all social and ads providers, plus any future ones). The flow is:

    1. Create a Connection with the provider's app credentials
       (e.g. ``client_id``/``client_secret`` from the manifest's
       ``auth.oauth.credential_fields``).
    2. Redirect the user to ``OAuthService.get_authorize_url(connection, redirect_uri)``.
       The connection pk and redirect_uri travel in a signed ``state`` token.
    3. The provider redirects back to the ``oauth_callback`` view, which calls
       ``OAuthService.complete_authorization(state, code)`` — the exchanged
       tokens are merged into the connection's encrypted credentials and the
       connection is marked connected.
    4. When tokens expire, call ``OAuthService.refresh_tokens(connection)``.

Adapters return ``OAuthTokens.extra["credentials"]`` keyed by their own
credential field names, so the merge is provider-agnostic.
"""

from __future__ import annotations

import logging

from django.core import signing
from django.core.exceptions import ImproperlyConfigured

logger = logging.getLogger(__name__)

STATE_SALT = "django_bapp_connectors.oauth"


def _resolve_connection_model():
    from django.apps import apps

    from django_bapp_connectors.settings import get_setting

    model_path = get_setting("CONNECTION_MODEL")
    if not model_path:
        raise ImproperlyConfigured(
            'BAPP_CONNECTORS["CONNECTION_MODEL"] must be set to complete OAuth callbacks '
            '(e.g. "connectors.Connection").'
        )
    return apps.get_model(model_path)


class OAuthService:
    """Drives the OAuth2 lifecycle for OAuth-capable provider connections."""

    @staticmethod
    def _get_oauth_adapter(connection):
        from bapp_connectors.core.capabilities.oauth import OAuthCapability
        from bapp_connectors.core.errors import ConfigurationError
        from django_bapp_connectors.services.connection import ConnectionService

        adapter = ConnectionService.get_adapter(connection, log_execution=False)
        if not isinstance(adapter, OAuthCapability):
            raise ConfigurationError(
                f"Provider {connection.provider_family}/{connection.provider_name} "
                "does not support OAuth"
            )
        return adapter

    @staticmethod
    def get_authorize_url(connection, redirect_uri: str) -> str:
        """Build the provider authorization URL with a signed state token.

        The state binds the callback to this connection and carries the
        redirect_uri so the token exchange can reuse the exact same value
        (an OAuth2 requirement).
        """
        adapter = OAuthService._get_oauth_adapter(connection)
        state = signing.dumps(
            {"connection_id": connection.pk, "redirect_uri": redirect_uri},
            salt=STATE_SALT,
        )
        return adapter.get_authorize_url(redirect_uri, state=state)

    @staticmethod
    def complete_authorization(state: str, code: str, connection_model=None):
        """Exchange the callback code for tokens and store them on the connection.

        Raises ``signing.BadSignature`` for tampered/expired state and the
        connection model's ``DoesNotExist`` for stale connection ids.
        Returns the updated connection, marked as connected.
        """
        from django_bapp_connectors.settings import get_setting

        payload = signing.loads(
            state, salt=STATE_SALT, max_age=get_setting("OAUTH_STATE_MAX_AGE")
        )
        model = connection_model or _resolve_connection_model()
        connection = model.objects.get(pk=payload["connection_id"])

        adapter = OAuthService._get_oauth_adapter(connection)
        tokens = adapter.exchange_code_for_token(code, payload["redirect_uri"], state=state)

        OAuthService.apply_tokens(connection, tokens)
        connection.mark_connected()
        logger.info(
            "OAuth authorization completed for connection %s (%s/%s)",
            connection.pk,
            connection.provider_family,
            connection.provider_name,
        )
        return connection

    @staticmethod
    def refresh_tokens(connection):
        """Refresh the connection's stored tokens through its adapter.

        Providers with refresh tokens get the stored ``refresh_token``;
        Meta-style providers (no refresh tokens) get the current access
        token for their long-lived exchange grant.
        """
        adapter = OAuthService._get_oauth_adapter(connection)
        creds = connection.credentials
        current = creds.get("refresh_token") or creds.get("token") or creds.get("access_token") or ""
        tokens = adapter.refresh_token(current)
        OAuthService.apply_tokens(connection, tokens)
        return tokens

    @staticmethod
    def apply_tokens(connection, tokens) -> None:
        """Merge exchanged/refreshed tokens into the connection's credentials.

        Prefers the adapter-provided ``extra["credentials"]`` mapping (keys
        already match the provider's credential field names); falls back to
        generic ``access_token``/``refresh_token`` keys.
        """
        new_creds = (tokens.extra or {}).get("credentials") or {}
        if not new_creds:
            new_creds = {"access_token": tokens.access_token}
            if tokens.refresh_token:
                new_creds["refresh_token"] = tokens.refresh_token
        connection.credentials = {**connection.credentials, **new_creds}
        connection.save(update_fields=["credentials_encrypted", "updated_at"])
