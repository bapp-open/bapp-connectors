"""
Google Gemini LLM provider manifest.

Uses the Gemini API (generativelanguage.googleapis.com).
Auth via API key in header (x-goog-api-key).
"""

from bapp_connectors.core.capabilities import EmbeddingCapability
from bapp_connectors.core.manifest import (
    AuthConfig,
    CredentialField,
    ProviderManifest,
    RateLimitConfig,
    RetryConfig,
    SettingsConfig,
    SettingsField,
)
from bapp_connectors.core.ports import LLMPort
from bapp_connectors.core.types import AuthStrategy, BackoffStrategy, FieldType, ProviderFamily

manifest = ProviderManifest(
    name="gemini",
    family=ProviderFamily.LLM,
    display_name="Google Gemini",
    description="Google Gemini models for chat completion, embeddings, and multimodal content.",
    base_url="https://generativelanguage.googleapis.com/v1beta/",
    auth=AuthConfig(
        strategy=AuthStrategy.CUSTOM,
        required_fields=[
            CredentialField(
                name="api_key",
                label="API Key",
                sensitive=True,
                required=False,
                help_text="Google AI API key. Leave empty to use platform-provided key.",
            ),
        ],
    ),
    settings=SettingsConfig(
        fields=[
            SettingsField(
                name="default_model",
                label="Default Model",
                field_type=FieldType.SELECT,
                choices=["gemini-2.5-flash-preview-05-20", "gemini-2.5-pro-preview-05-06", "gemini-2.0-flash"],
                default="gemini-2.0-flash",
                help_text="Model to use when none is specified.",
            ),
            SettingsField(
                name="temperature",
                label="Default Temperature",
                field_type=FieldType.STR,
                default="1.0",
                help_text="Default sampling temperature.",
            ),
            SettingsField(
                name="platform_api_key",
                label="Platform API Key",
                field_type=FieldType.STR,
                required=False,
                help_text="Platform-level API key used when tenant does not provide their own.",
            ),
        ],
    ),
    capabilities=[LLMPort, EmbeddingCapability],
    rate_limit=RateLimitConfig(
        requests_per_second=15,
        burst=30,
    ),
    retry=RetryConfig(
        max_retries=3,
        backoff=BackoffStrategy.EXPONENTIAL,
        retryable_status_codes=[429, 500, 502, 503, 504],
        non_retryable_status_codes=[400, 401, 403, 404],
    ),
)
