"""
Abstract execution log model — audit trail for every adapter call.
"""

from __future__ import annotations

from django.db import models


class AbstractExecutionLog(models.Model):
    """
    Audit trail for every adapter API call.

    Subclass and add your connection FK:

        class ExecutionLog(AbstractExecutionLog):
            connection = models.ForeignKey('myapp.ShopConnection', on_delete=models.CASCADE)
    """

    action = models.CharField(max_length=100, db_index=True)
    method = models.CharField(max_length=10, blank=True, default="")
    url = models.CharField(max_length=500, blank=True, default="")
    request_payload = models.JSONField(null=True, blank=True)
    response_status = models.IntegerField(null=True, blank=True)
    response_payload = models.JSONField(null=True, blank=True)
    duration_ms = models.IntegerField(null=True, blank=True)
    error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True
        ordering = ["-created_at"]

    def __str__(self):
        return f"ExecutionLog({self.action}, {self.method} {self.url}, {self.response_status})"
