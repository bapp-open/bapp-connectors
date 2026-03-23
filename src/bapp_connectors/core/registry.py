"""
Provider registry — central registration and discovery of provider adapters.

Validates manifests and adapter contracts on registration.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from bapp_connectors.core.errors import ConfigurationError
from bapp_connectors.core.http import RateLimiter, ResilientHttpClient, RetryPolicy
from bapp_connectors.core.http.auth import BaseAuthStrategy, BasicAuth, BearerAuth, NoAuth, TokenAuth
from bapp_connectors.core.manifest import ProviderManifest
from bapp_connectors.core.types import AuthStrategy

if TYPE_CHECKING:
    from bapp_connectors.core.ports.base import BasePort

logger = logging.getLogger(__name__)


class ProviderRegistry:
    """
    Central registry for all provider adapters.

    Validates manifest completeness and adapter contract compliance on registration.
    """

    def __init__(self):
        self._adapters: dict[str, type[BasePort]] = {}  # key = "family.name"

    def _key(self, family: str, provider: str) -> str:
        return f"{family}.{provider}"

    def register(self, adapter_cls: type[BasePort]) -> None:
        """
        Register an adapter class. Validates its manifest.

        Args:
            adapter_cls: The adapter class to register. Must have a `manifest` attribute.
        """
        manifest = getattr(adapter_cls, "manifest", None)
        if manifest is None:
            raise ConfigurationError(f"Adapter {adapter_cls.__name__} has no manifest attribute.")

        if not isinstance(manifest, ProviderManifest):
            raise ConfigurationError(f"Adapter {adapter_cls.__name__}.manifest must be a ProviderManifest instance.")

        errors = manifest.validate()
        if errors:
            raise ConfigurationError(f"Invalid manifest for {adapter_cls.__name__}: {'; '.join(errors)}")

        # Validate that the adapter implements all declared capabilities
        for cap in manifest.capabilities:
            if not issubclass(adapter_cls, cap):
                raise ConfigurationError(
                    f"Adapter {adapter_cls.__name__} declares capability {cap.__name__} but does not implement it."
                )

        key = self._key(manifest.family.value, manifest.name)
        if key in self._adapters:
            logger.warning("Overwriting existing adapter registration for %s", key)

        self._adapters[key] = adapter_cls
        logger.info("Registered adapter: %s (%s)", key, adapter_cls.__name__)

    def get_adapter_class(self, family: str, provider: str) -> type[BasePort]:
        """Get the adapter class for a given family and provider name."""
        key = self._key(family, provider)
        if key not in self._adapters:
            raise ConfigurationError(f"No adapter registered for '{key}'.")
        return self._adapters[key]

    def create_adapter(
        self,
        family: str,
        provider: str,
        credentials: dict,
        **kwargs: Any,
    ) -> BasePort:
        """
        Instantiate an adapter with credentials and a pre-configured HTTP client.

        The adapter's __init__ receives: credentials dict, http_client, and any extra kwargs.
        """
        cls = self.get_adapter_class(family, provider)
        manifest = cls.manifest

        # Validate credentials
        missing = manifest.auth.validate_credentials(credentials)
        if missing:
            raise ConfigurationError(f"Missing credential fields: {', '.join(missing)}")

        # Build auth strategy
        auth = self._build_auth(manifest.auth.strategy, credentials)

        # Build HTTP client
        retry_policy = RetryPolicy(
            max_retries=manifest.retry.max_retries,
            backoff=manifest.retry.backoff,
            base_delay=manifest.retry.base_delay,
            max_delay=manifest.retry.max_delay,
            retryable_status_codes=set(manifest.retry.retryable_status_codes),
            non_retryable_status_codes=set(manifest.retry.non_retryable_status_codes),
        )

        rate_limiter = RateLimiter(
            requests_per_second=manifest.rate_limit.requests_per_second,
            burst=manifest.rate_limit.burst,
        )

        http_client = ResilientHttpClient(
            base_url=manifest.base_url,
            auth=auth,
            retry_policy=retry_policy,
            rate_limiter=rate_limiter,
            provider_name=manifest.name,
        )

        return cls(credentials=credentials, http_client=http_client, **kwargs)

    def _build_auth(self, strategy: AuthStrategy, credentials: dict) -> BaseAuthStrategy:
        """Build the auth strategy from manifest + credentials."""
        if strategy == AuthStrategy.BASIC:
            return BasicAuth(
                username=credentials.get("username", ""),
                password=credentials.get("password", ""),
            )
        if strategy == AuthStrategy.BEARER:
            return BearerAuth(token=credentials.get("token", ""))
        if strategy == AuthStrategy.TOKEN:
            return TokenAuth(token=credentials.get("token", ""))
        if strategy == AuthStrategy.NONE:
            return NoAuth()
        # CUSTOM, API_KEY, OAUTH2 — adapter handles its own auth
        return NoAuth()

    def list_providers(self, family: str | None = None) -> list[ProviderManifest]:
        """List all registered provider manifests, optionally filtered by family."""
        manifests = []
        for _key, cls in self._adapters.items():
            manifest = cls.manifest
            if family is None or manifest.family.value == family:
                manifests.append(manifest)
        return manifests

    def get_manifest(self, family: str, provider: str) -> ProviderManifest:
        """Get the manifest for a specific provider."""
        cls = self.get_adapter_class(family, provider)
        return cls.manifest

    def is_registered(self, family: str, provider: str) -> bool:
        """Check if a provider is registered."""
        return self._key(family, provider) in self._adapters


# Global registry instance
registry = ProviderRegistry()
