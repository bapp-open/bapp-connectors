"""
DTOs for product sync operations.
"""

from __future__ import annotations

from pydantic import BaseModel

from bapp_connectors.core.dto.base import BaseDTO


class SyncError(BaseDTO):
    """A single sync error for a product."""

    product_id: str = ""
    error: str = ""
    retryable: bool = False


class SyncResult(BaseModel):
    """Accumulator for sync operation results. Mutable (not frozen)."""

    created: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[SyncError] = []


class CategoryMapping(BaseModel):
    """A local-to-remote category ID mapping produced by push_categories."""

    local_id: str
    remote_id: str
    name: str = ""
