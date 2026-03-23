"""
Abstract webhook event model — persists every incoming webhook for audit and deduplication.
"""

from __future__ import annotations

from django.db import models


class AbstractWebhookEvent(models.Model):
    """
    Persists every incoming webhook for audit and deduplication.

    Subclass and add your connection FK:

        class WebhookEvent(AbstractWebhookEvent):
            connection = models.ForeignKey('myapp.ShopConnection', on_delete=models.CASCADE, null=True)
    """

    provider = models.CharField(max_length=50, db_index=True)
    event_type = models.CharField(max_length=100, db_index=True)
    idempotency_key = models.CharField(max_length=255, unique=True)
    payload = models.JSONField(default=dict)
    headers = models.JSONField(default=dict)
    signature_valid = models.BooleanField(null=True)
    status = models.CharField(max_length=20, default="received", db_index=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True
        indexes = [
            models.Index(fields=["provider", "event_type"]),
            models.Index(fields=["status", "created_at"]),
        ]

    def __str__(self):
        return f"WebhookEvent({self.provider}:{self.event_type}, status={self.status})"

    @property
    def is_duplicate(self) -> bool:
        return self.status == "duplicate"

    def mark_processing(self):
        self.status = "processing"
        self.save(update_fields=["status"])

    def mark_processed(self):
        from django.utils import timezone

        self.status = "processed"
        self.processed_at = timezone.now()
        self.save(update_fields=["status", "processed_at"])

    def mark_failed(self, error: str):
        self.status = "failed"
        self.error = error[:2000]
        self.save(update_fields=["status", "error"])

    def mark_duplicate(self):
        self.status = "duplicate"
        self.save(update_fields=["status"])
