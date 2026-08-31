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
    code: str = ""
    retryable: bool = False
    extra: dict = {}


class SyncResult(BaseModel):
    """Accumulator for sync operation results. Mutable (not frozen)."""

    created: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[SyncError] = []
    remote_ids: dict[str, str] = {}       # local product_id -> remote id (created AND updated)
    remote_meta: dict[str, dict] = {}     # local product_id -> {"date_modified_gmt": ...}


class CategoryMapping(BaseModel):
    """A local-to-remote category ID mapping produced by push_categories."""

    local_id: str
    remote_id: str
    name: str = ""


class CategorySyncResult(BaseModel):
    """Result of a category sync: newly created mappings + local ids updated remotely."""

    created: list[CategoryMapping] = []
    updated: list[str] = []
