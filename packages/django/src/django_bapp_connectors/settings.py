"""
Default settings for django_bapp_connectors.

Override in your project's Django settings:

    BAPP_CONNECTORS = {
        "ENCRYPTION_KEY": "your-fernet-key",
        "WEBHOOK_BASE_URL": "https://example.com/webhooks/",
    }
"""

from __future__ import annotations

from django.conf import settings

DEFAULTS = {
    "ENCRYPTION_KEY": "",
    "WEBHOOK_BASE_URL": "",
    "DEFAULT_TIMEOUT": 10,
    "CONNECTION_MODEL": "",  # e.g. "connectors.Connection"
    "WEBHOOK_EVENT_MODEL": "",  # e.g. "connectors.WebhookEvent"
    "OAUTH_STATE_MAX_AGE": 900,  # seconds an OAuth state token stays valid
    "OAUTH_SUCCESS_REDIRECT": "",  # user-facing URL after a completed OAuth callback
    "OAUTH_ERROR_REDIRECT": "",  # user-facing URL after a failed OAuth callback
}


def get_setting(name: str):
    """Get a connector setting, falling back to defaults."""
    user_settings = getattr(settings, "BAPP_CONNECTORS", {})
    return user_settings.get(name, DEFAULTS.get(name))
