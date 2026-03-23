"""
Abstract connection model — subclass and add your tenant FK.

Includes circuit-breaker logic: connections that hit consecutive auth failures
are automatically marked as disconnected and disabled to prevent cron loops.
"""

from __future__ import annotations

import logging

from django.db import models
from django.utils import timezone

from django_bapp_connectors.encryption import decrypt_value, encrypt_value

logger = logging.getLogger(__name__)

# After this many consecutive auth failures, disable the connection
AUTH_FAILURE_THRESHOLD = 3


class AbstractConnection(models.Model):
    """
    Stores a provider connection configuration for a tenant.

    Subclass this and add your tenant FK:

        class ShopConnection(AbstractConnection):
            company = models.ForeignKey('company.Company', on_delete=models.CASCADE)

    Circuit-breaker behavior:
    - On AuthenticationError: increment auth_failure_count
    - When auth_failure_count >= AUTH_FAILURE_THRESHOLD: set is_connected=False, is_enabled=False
    - Cron tasks should check is_enabled + is_connected before running
    - Re-enabling requires manual action (fix credentials, re-test)
    """

    provider_family = models.CharField(max_length=50, db_index=True)
    provider_name = models.CharField(max_length=50, db_index=True)
    display_name = models.CharField(max_length=200, blank=True)
    credentials_encrypted = models.TextField(blank=True, default="")
    config = models.JSONField(default=dict, blank=True)
    is_enabled = models.BooleanField(default=True, db_index=True)
    is_connected = models.BooleanField(default=False, db_index=True)

    # Circuit breaker fields
    auth_failure_count = models.IntegerField(default=0)
    last_auth_failure_at = models.DateTimeField(null=True, blank=True)
    disabled_reason = models.CharField(max_length=500, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

    def __str__(self):
        return f"{self.display_name or self.provider_name} ({self.provider_family})"

    @property
    def is_operational(self) -> bool:
        """Check if this connection is ready to be used by cron/sync tasks."""
        return self.is_enabled and self.is_connected

    @property
    def credentials(self) -> dict:
        """Decrypt and return credentials."""
        if not self.credentials_encrypted:
            return {}
        return decrypt_value(self.credentials_encrypted)

    @credentials.setter
    def credentials(self, value: dict):
        """Encrypt and store credentials."""
        self.credentials_encrypted = encrypt_value(value)

    def get_adapter(self):
        """
        Instantiate the matching bapp_connectors adapter.

        Returns a configured adapter instance ready for API calls.
        """
        from bapp_connectors.core.registry import registry

        return registry.create_adapter(
            family=self.provider_family,
            provider=self.provider_name,
            credentials=self.credentials,
            config=self.config,
        )

    def test_connection(self):
        """Test the connection and update is_connected status."""
        adapter = self.get_adapter()
        result = adapter.test_connection()
        if result.success:
            self.mark_connected()
        else:
            self.record_auth_failure(result.message)
        return result

    def record_auth_failure(self, reason: str = ""):
        """
        Record an authentication failure. Auto-disables after threshold.

        Call this from your Celery tasks when you catch AuthenticationError.
        """
        self.auth_failure_count += 1
        self.last_auth_failure_at = timezone.now()
        self.is_connected = False
        update_fields = ["auth_failure_count", "last_auth_failure_at", "is_connected", "updated_at"]

        if self.auth_failure_count >= AUTH_FAILURE_THRESHOLD:
            self.is_enabled = False
            self.disabled_reason = f"Auto-disabled after {self.auth_failure_count} consecutive auth failures. Last: {reason[:400]}"
            update_fields.extend(["is_enabled", "disabled_reason"])
            logger.warning(
                "Connection %s (%s/%s) auto-disabled after %d auth failures",
                self.pk,
                self.provider_family,
                self.provider_name,
                self.auth_failure_count,
            )

        self.save(update_fields=update_fields)

    def mark_connected(self):
        """Mark connection as successful, reset failure counter."""
        self.is_connected = True
        self.auth_failure_count = 0
        self.last_auth_failure_at = None
        self.disabled_reason = ""
        self.save(update_fields=[
            "is_connected", "auth_failure_count", "last_auth_failure_at",
            "disabled_reason", "updated_at",
        ])

    def re_enable(self):
        """Manually re-enable a disabled connection (after fixing credentials)."""
        self.is_enabled = True
        self.auth_failure_count = 0
        self.disabled_reason = ""
        self.save(update_fields=["is_enabled", "auth_failure_count", "disabled_reason", "updated_at"])
