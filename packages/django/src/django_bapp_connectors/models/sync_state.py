"""
Abstract sync state model — tracks cursor-based incremental sync.
"""

from __future__ import annotations

from django.db import models


class AbstractSyncState(models.Model):
    """
    Tracks cursor-based incremental sync per connection per resource type.

    Subclass and add your connection FK:

        class SyncState(AbstractSyncState):
            connection = models.ForeignKey('myapp.ShopConnection', on_delete=models.CASCADE)
    """

    resource_type = models.CharField(max_length=50, db_index=True)
    cursor = models.CharField(max_length=500, blank=True, default="")
    last_sync_at = models.DateTimeField(null=True, blank=True)
    next_sync_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, default="idle")
    error_count = models.IntegerField(default=0)
    last_error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

    def __str__(self):
        return f"SyncState({self.resource_type}, status={self.status})"

    def mark_running(self):
        self.status = "running"
        self.save(update_fields=["status", "updated_at"])

    def mark_completed(self, cursor: str = "", last_sync_at=None):
        from django.utils import timezone

        self.status = "completed"
        self.error_count = 0
        self.last_error = ""
        if cursor:
            self.cursor = cursor
        self.last_sync_at = last_sync_at or timezone.now()
        self.save(update_fields=["status", "cursor", "last_sync_at", "error_count", "last_error", "updated_at"])

    def mark_failed(self, error: str):
        self.status = "failed"
        self.error_count += 1
        self.last_error = error[:2000]
        self.save(update_fields=["status", "error_count", "last_error", "updated_at"])
