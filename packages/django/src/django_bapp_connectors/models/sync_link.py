"""
Abstract sync link — persistent local↔remote id mapping with change-detection hashes.

Subclass and add your connection FK:

    class SyncLink(AbstractSyncLink):
        connection = models.ForeignKey('myapp.Connection', on_delete=models.CASCADE, related_name='sync_links')

        class Meta:
            constraints = [
                models.UniqueConstraint(fields=['connection', 'resource_type', 'local_id'], name='uniq_synclink_local'),
            ]
"""

from __future__ import annotations

from django.db import models
from django.utils import timezone


class AbstractSyncLink(models.Model):
    STATUS_PENDING = "pending"
    STATUS_LINKED = "linked"
    STATUS_ERROR = "error"
    STATUS_SKIPPED = "skipped"
    STATUS_CONFLICT = "conflict"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_LINKED, "Linked"),
        (STATUS_ERROR, "Error"),
        (STATUS_SKIPPED, "Skipped"),
        (STATUS_CONFLICT, "Conflict"),
    ]

    resource_type = models.CharField(max_length=50, db_index=True)
    local_id = models.CharField(max_length=64)
    remote_id = models.CharField(max_length=64, blank=True, default="", db_index=True)
    content_hash = models.CharField(max_length=64, blank=True, default="")   # hash of the local payload last sent/applied
    remote_hash = models.CharField(max_length=64, blank=True, default="")    # provider's modified marker last seen
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True)
    last_error = models.TextField(blank=True, default="")
    last_pushed_at = models.DateTimeField(null=True, blank=True)
    last_pulled_at = models.DateTimeField(null=True, blank=True)
    extra = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

    def __str__(self):
        return f"SyncLink({self.resource_type} {self.local_id} -> {self.remote_id or '?'}, {self.status})"

    def _merge_extra(self, extra: dict | None) -> None:
        if extra:
            merged = dict(self.extra or {})
            merged.update(extra)
            self.extra = merged

    def mark_linked(self, *, remote_id=None, content_hash=None, remote_hash=None, pushed=False, pulled=False, extra=None):
        now = timezone.now()
        if remote_id:
            self.remote_id = str(remote_id)
        if content_hash is not None:
            self.content_hash = content_hash
        if remote_hash is not None:
            self.remote_hash = str(remote_hash)
        if pushed:
            self.last_pushed_at = now
        if pulled:
            self.last_pulled_at = now
        self.status = self.STATUS_LINKED
        self.last_error = ""
        self._merge_extra(extra)
        self.save(update_fields=[
            "remote_id", "content_hash", "remote_hash", "last_pushed_at", "last_pulled_at",
            "status", "last_error", "extra", "updated_at",
        ])

    def mark_error(self, error: str, *, extra=None):
        self.status = self.STATUS_ERROR
        self.last_error = (error or "")[:2000]
        self._merge_extra(extra)
        self.save(update_fields=["status", "last_error", "extra", "updated_at"])

    def mark_skipped(self, reason: str):
        self.status = self.STATUS_SKIPPED
        self.last_error = ""
        self._merge_extra({"skip_reason": reason})
        self.save(update_fields=["status", "last_error", "extra", "updated_at"])

    def mark_conflict(self, reason: str):
        self.status = self.STATUS_CONFLICT
        self.last_error = (reason or "")[:2000]
        self.save(update_fields=["status", "last_error", "updated_at"])
