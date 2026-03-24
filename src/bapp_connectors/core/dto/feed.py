"""
Normalized DTOs for product feed generation.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class FeedWarning(BaseModel):
    """A non-fatal warning about a product in the feed."""

    model_config = ConfigDict(frozen=True)

    product_id: str
    field: str
    message: str
    severity: str = "warning"  # "warning" | "info"


class FeedValidationError(BaseModel):
    """A validation error for a specific product."""

    model_config = ConfigDict(frozen=True)

    product_id: str
    field: str
    message: str
    required: bool = True  # True = hard error, False = missing recommended field


class FeedResult(BaseModel):
    """Result of generating a product feed."""

    model_config = ConfigDict(frozen=True)

    content: str | bytes
    format: str  # "xml", "csv", "json"
    content_type: str  # MIME type
    product_count: int
    skipped_count: int = 0
    warnings: list[FeedWarning] = []
    generated_at: datetime | None = None


class FeedValidationResult(BaseModel):
    """Result of validating products against feed platform requirements."""

    model_config = ConfigDict(frozen=True)

    valid_count: int
    invalid_count: int
    errors: list[FeedValidationError] = []


class FeedUploadResult(BaseModel):
    """Result of uploading a feed to a platform API."""

    model_config = ConfigDict(frozen=True)

    success: bool
    message: str = ""
    items_accepted: int = 0
    items_rejected: int = 0
    details: dict = {}
