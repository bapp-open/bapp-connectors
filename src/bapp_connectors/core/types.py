"""
Core enums and type definitions for the connector framework.
"""

from __future__ import annotations

from enum import StrEnum


class ProviderFamily(StrEnum):
    """The high-level family a provider belongs to."""

    SHOP = "shop"
    COURIER = "courier"
    PAYMENT = "payment"
    MESSAGING = "messaging"
    STORAGE = "storage"
    LLM = "llm"


class BackoffStrategy(StrEnum):
    """Retry backoff strategies."""

    NONE = "none"
    LINEAR = "linear"
    EXPONENTIAL = "exponential"


class AuthStrategy(StrEnum):
    """Authentication strategies supported by the framework."""

    NONE = "none"
    BASIC = "basic"
    TOKEN = "token"
    BEARER = "bearer"
    API_KEY = "api_key"
    OAUTH2 = "oauth2"
    CUSTOM = "custom"


class FieldType(StrEnum):
    """Field types for provider settings, used for UI rendering."""

    STR = "str"
    BOOL = "bool"
    INT = "int"
    SELECT = "select"
    TEXTAREA = "textarea"


class SyncStatus(StrEnum):
    """Status of a sync operation."""

    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class WebhookEventStatus(StrEnum):
    """Processing status of an incoming webhook event."""

    RECEIVED = "received"
    PROCESSING = "processing"
    PROCESSED = "processed"
    FAILED = "failed"
    DUPLICATE = "duplicate"
