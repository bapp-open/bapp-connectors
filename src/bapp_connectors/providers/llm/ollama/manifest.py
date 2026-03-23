"""
Ollama LLM provider manifest.

Ollama runs models locally — no API key needed, just a base URL.
"""

from bapp_connectors.core.capabilities import EmbeddingCapability
from bapp_connectors.core.manifest import (
    AuthConfig,
    ProviderManifest,
    RateLimitConfig,
    RetryConfig,
    SettingsConfig,
    SettingsField,
)
from bapp_connectors.core.ports import LLMPort
from bapp_connectors.core.types import AuthStrategy, BackoffStrategy, FieldType, ProviderFamily

manifest = ProviderManifest(
    name="ollama",
    family=ProviderFamily.LLM,
    display_name="Ollama",
    description="Ollama local LLM server for running open-source models (Llama, Mistral, Gemma, etc.).",
    base_url="http://localhost:11434/",
    auth=AuthConfig(
        strategy=AuthStrategy.NONE,
        required_fields=[],
    ),
    settings=SettingsConfig(
        fields=[
            SettingsField(
                name="base_url",
                label="Ollama Server URL",
                field_type=FieldType.STR,
                default="http://localhost:11434",
                help_text="URL of the Ollama server.",
            ),
            SettingsField(
                name="default_model",
                label="Default Model",
                field_type=FieldType.STR,
                default="llama3.2",
                help_text="Model to use when none is specified (e.g. llama3.2, mistral, gemma2).",
            ),
            SettingsField(
                name="temperature",
                label="Default Temperature",
                field_type=FieldType.STR,
                default="0.7",
                help_text="Default sampling temperature.",
            ),
        ],
    ),
    capabilities=[LLMPort, EmbeddingCapability],
    rate_limit=RateLimitConfig(
        requests_per_second=10,
        burst=20,
    ),
    retry=RetryConfig(
        max_retries=2,
        backoff=BackoffStrategy.EXPONENTIAL,
        retryable_status_codes=[429, 500, 502, 503, 504],
        non_retryable_status_codes=[400, 404],
    ),
)
