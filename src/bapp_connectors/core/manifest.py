"""
Provider manifest — declarative description of a provider's capabilities, auth, rate limits, and webhooks.

Every provider must define a manifest. The registry validates it on registration.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from bapp_connectors.core.types import AuthStrategy, BackoffStrategy, FieldType, ProviderFamily


@dataclass
class CredentialField:
    """A single credential field required by the provider."""

    name: str
    label: str = ""
    sensitive: bool = False
    required: bool = True
    default: str = ""
    choices: list[str] | None = None
    help_text: str = ""

    def __post_init__(self):
        if not self.label:
            self.label = self.name.replace("_", " ").title()


@dataclass
class SettingsField:
    """A single tenant-configurable setting for the provider."""

    name: str
    label: str = ""
    field_type: FieldType = FieldType.STR
    required: bool = False
    default: str | bool | int | None = None
    choices: list[str] | None = None
    help_text: str = ""
    description: str = ""

    def __post_init__(self):
        if not self.label:
            self.label = self.name.replace("_", " ").title()


@dataclass
class SettingsConfig:
    """Provider settings configuration — tenant-level options separate from auth."""

    fields: list[SettingsField] = field(default_factory=list)

    def validate_settings(self, config: dict) -> list[str]:
        """Validate that required settings are present and choices are respected. Returns error messages."""
        errors = []
        for f in self.fields:
            value = config.get(f.name)
            if f.required and (value is None or value == ""):
                errors.append(f"Missing required setting: {f.name}")
            if value is not None and f.choices and str(value) not in f.choices:
                errors.append(f"Invalid value for {f.name}: '{value}'. Must be one of: {f.choices}")
        return errors

    def apply_defaults(self, config: dict) -> dict:
        """Return a copy of config with defaults filled in for missing fields."""
        result = dict(config)
        for f in self.fields:
            if f.name not in result and f.default is not None:
                result[f.name] = f.default
        return result


@dataclass
class AuthConfig:
    """Authentication configuration for a provider."""

    strategy: AuthStrategy = AuthStrategy.NONE
    required_fields: list[CredentialField] = field(default_factory=list)

    def validate_credentials(self, credentials: dict) -> list[str]:
        """Validate that all required fields are present. Returns list of missing field names."""
        missing = []
        for f in self.required_fields:
            if f.required and not credentials.get(f.name):
                missing.append(f.name)
        return missing


@dataclass
class RateLimitConfig:
    """Rate limit configuration for a provider."""

    requests_per_second: float = 10.0
    burst: int = 10


@dataclass
class RetryConfig:
    """Retry configuration for a provider."""

    max_retries: int = 3
    backoff: BackoffStrategy = BackoffStrategy.EXPONENTIAL
    base_delay: float = 1.0
    max_delay: float = 60.0
    retryable_status_codes: list[int] = field(default_factory=lambda: [429, 500, 502, 503, 504])
    non_retryable_status_codes: list[int] = field(default_factory=lambda: [400, 401, 403, 404])


@dataclass
class WebhookConfig:
    """Webhook configuration for a provider."""

    supported: bool = False
    signature_method: str | None = None  # 'hmac-sha256', 'hmac-sha1', None
    signature_header: str = ""  # e.g., 'X-Hub-Signature-256'
    events: list[str] = field(default_factory=list)


@dataclass
class ProviderManifest:
    """
    Declarative manifest for a provider adapter.

    Defines everything the framework needs to know about a provider:
    name, family, capabilities, auth, rate limits, retry policy, webhook config.
    """

    name: str
    family: ProviderFamily
    display_name: str = ""
    description: str = ""
    base_url: str = ""

    auth: AuthConfig = field(default_factory=AuthConfig)
    settings: SettingsConfig = field(default_factory=SettingsConfig)
    capabilities: list[type] = field(default_factory=list)
    rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig)
    retry: RetryConfig = field(default_factory=RetryConfig)
    webhooks: WebhookConfig = field(default_factory=WebhookConfig)

    def __post_init__(self):
        if not self.display_name:
            self.display_name = self.name.replace("_", " ").title()

    def validate(self) -> list[str]:
        """Validate the manifest. Returns a list of error messages (empty = valid)."""
        errors = []
        if not self.name:
            errors.append("Manifest must have a name.")
        if not self.family:
            errors.append("Manifest must declare a family.")
        if not self.base_url:
            errors.append("Manifest must declare a base_url.")
        return errors
