"""Minimal Django settings for running django_bapp_connectors tests."""

SECRET_KEY = "test-secret-key-for-unit-tests-only"

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django_bapp_connectors",
    "tests.testapp",
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

BAPP_CONNECTORS = {
    "ENCRYPTION_KEY": "",
    "CONNECTION_MODEL": "testapp.Connection",
    "WEBHOOK_EVENT_MODEL": "testapp.WebhookEvent",
}
