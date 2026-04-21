"""
OpenAI LLM provider manifest.
"""

from bapp_connectors.core.capabilities import EmbeddingCapability, ImageGenerationCapability, TranscriptionCapability
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
    name="openai",
    family=ProviderFamily.LLM,
    display_name="OpenAI",
    description="OpenAI GPT models for chat completion, embeddings, and function calling.",
    base_url="https://api.openai.com/v1/",
    auth=AuthConfig(
        strategy=AuthStrategy.CUSTOM,
        required_fields=[
            CredentialField(
                name="api_key",
                label="API Key",
                sensitive=True,
                required=False,
                help_text="OpenAI API key. Leave empty to use platform-provided key.",
            ),
        ],
    ),
    settings=SettingsConfig(
        fields=[
            SettingsField(
                name="default_model",
                label="Default Model",
                field_type=FieldType.SELECT,
                choices=["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
                choices_source="list_models",
                default="gpt-4o-mini",
                help_text="Model to use when none is specified in the request.",
            ),
            SettingsField(
                name="temperature",
                label="Default Temperature",
                field_type=FieldType.STR,
                default="0.7",
                help_text="Default sampling temperature (0.0 - 2.0).",
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
    capabilities=[LLMPort, EmbeddingCapability, TranscriptionCapability, ImageGenerationCapability],
    rate_limit=RateLimitConfig(
        requests_per_second=50,
        burst=100,
    ),
    retry=RetryConfig(
        max_retries=3,
        backoff=BackoffStrategy.EXPONENTIAL,
        retryable_status_codes=[429, 500, 502, 503, 504],
        non_retryable_status_codes=[400, 401, 403, 404],
    ),
)
