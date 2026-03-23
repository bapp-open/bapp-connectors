"""
Base DTO and shared types for normalized data transfer objects.
"""

from __future__ import annotations

from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class ProviderMeta(BaseModel):
    """Preserved raw data from the provider for debugging/audit."""

    model_config = ConfigDict(frozen=True)

    provider: str
    raw_id: str = ""
    raw_payload: dict = {}
    fetched_at: datetime | None = None


class BaseDTO(BaseModel):
    """All DTOs carry optional provider metadata for traceability."""

    model_config = ConfigDict(frozen=True)

    provider_meta: ProviderMeta | None = None


class PaginatedResult(BaseModel, Generic[T]):
    """Cursor-based paginated result from a provider."""

    items: list[T]
    cursor: str | None = None
    has_more: bool = False
    total: int | None = None


class ConnectionTestResult(BaseModel):
    """Result of a connection test."""

    success: bool
    message: str = ""
    details: dict = {}


class BulkResult(BaseModel):
    """Result of a bulk operation."""

    total: int = 0
    succeeded: int = 0
    failed: int = 0
    errors: list[dict] = []
