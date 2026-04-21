"""
Anthropic LLM provider manifest.
"""

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
    name="anthropic",
    family=ProviderFamily.LLM,
    display_name="Anthropic",
    description="Anthropic Claude models for chat completion and function calling.",
    base_url="https://api.anthropic.com/v1/",
    auth=AuthConfig(
        strategy=AuthStrategy.CUSTOM,
        required_fields=[
            CredentialField(
                name="api_key",
                label="API Key",
                sensitive=True,
                required=False,
                help_text="Anthropic API key. Leave empty to use platform-provided key.",
            ),
        ],
    ),
    settings=SettingsConfig(
        fields=[
            SettingsField(
                name="default_model",
                label="Default Model",
                field_type=FieldType.SELECT,
                choices=[
                    "claude-opus-4-7",
                    "claude-sonnet-4-6",
                    "claude-haiku-4-5-20251001",
                    "claude-opus-4-20250514",
                    "claude-sonnet-4-20250514",
                ],
                default="claude-sonnet-4-6",
                help_text="Model to use when none is specified in the request.",
            ),
            SettingsField(
                name="max_tokens",
                label="Default Max Tokens",
                field_type=FieldType.INT,
                default=4096,
                help_text="Default maximum tokens in the response.",
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
    capabilities=[LLMPort],
    rate_limit=RateLimitConfig(
        requests_per_second=10,
        burst=20,
    ),
    retry=RetryConfig(
        max_retries=3,
        backoff=BackoffStrategy.EXPONENTIAL,
        retryable_status_codes=[429, 500, 502, 503, 504, 529],
        non_retryable_status_codes=[400, 401, 403, 404],
    ),
)
