"""
Connection service — adapter instantiation, connection testing, credential management.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from typing import TYPE_CHECKING, Any

from bapp_connectors.core.registry import registry
from bapp_connectors.core.types import ProviderFamily

if TYPE_CHECKING:
    from bapp_connectors.core.dto import ConnectionTestResult
    from bapp_connectors.core.manifest import CredentialField, ProviderManifest, SettingsField
    from bapp_connectors.core.ports import BasePort

logger = logging.getLogger(__name__)

_providers_loaded = False

# Default display metadata per family.  Projects may override via
# ``ConnectionService.get_available_providers(family_meta={...})``.
FAMILY_DEFAULTS: dict[str, dict[str, str]] = {
    ProviderFamily.SHOP:      {"label": "E-commerce & Shops",   "icon": "fad fa-store",            "color": "#ec4899"},
    ProviderFamily.COURIER:   {"label": "Courier & Shipping",   "icon": "fad fa-truck",            "color": "#f59e0b"},
    ProviderFamily.PAYMENT:   {"label": "Payment Gateways",     "icon": "fad fa-credit-card",      "color": "#10b981"},
    ProviderFamily.MESSAGING: {"label": "Messaging & Email",    "icon": "fad fa-comment-dots",     "color": "#3b82f6"},
    ProviderFamily.STORAGE:   {"label": "File Storage",         "icon": "fad fa-cloud-upload-alt", "color": "#8b5cf6"},
    ProviderFamily.LLM:       {"label": "AI & Language Models", "icon": "fad fa-brain",            "color": "#6366f1"},
    ProviderFamily.FEED:      {"label": "Product Feeds",        "icon": "fad fa-rss",              "color": "#ef4444"},
}


def ensure_providers_loaded() -> None:
    """Import every provider sub-package so adapters auto-register in the global registry.

    Safe to call multiple times — only runs the import scan once.
    """
    global _providers_loaded
    if _providers_loaded:
        return
    try:
        import bapp_connectors.providers as _pkg
    except ImportError:
        logger.warning("bapp_connectors.providers package not found — no providers will be available.")
        _providers_loaded = True
        return

    for _importer, modname, ispkg in pkgutil.walk_packages(_pkg.__path__, prefix=_pkg.__name__ + "."):
        if ispkg:
            try:
                importlib.import_module(modname)
            except Exception:
                logger.debug("Could not import provider %s", modname, exc_info=True)
    _providers_loaded = True


def _serialize_credential_field(f: CredentialField) -> dict[str, Any]:
    return {
        "name": f.name,
        "label": f.label,
        "required": f.required,
        "sensitive": f.sensitive,
        "default": f.default,
        "choices": f.choices,
        "help_text": f.help_text,
    }


def _serialize_settings_field(f: SettingsField) -> dict[str, Any]:
    return {
        "name": f.name,
        "label": f.label,
        "field_type": f.field_type.value,
        "required": f.required,
        "default": f.default,
        "choices": f.choices,
        "help_text": f.help_text,
        "description": f.description,
    }


def _serialize_provider(manifest: ProviderManifest) -> dict[str, Any]:
    """Serialize a single ProviderManifest into a UI-ready dict."""
    return {
        "name": manifest.name,
        "family": manifest.family.value,
        "display_name": manifest.display_name,
        "description": manifest.description,
        "allow_multiple": manifest.allow_multiple,
        "auth": {
            "strategy": manifest.auth.strategy.value,
            "credential_fields": [_serialize_credential_field(f) for f in manifest.auth.required_fields],
            "has_oauth": manifest.auth.oauth is not None,
            "oauth_display_name": manifest.auth.oauth.display_name if manifest.auth.oauth else "",
            "oauth_scopes": manifest.auth.oauth.scopes if manifest.auth.oauth else [],
            "oauth_credential_fields": [
                _serialize_credential_field(f) for f in manifest.auth.oauth.credential_fields
            ] if manifest.auth.oauth else [],
        },
        "settings": [_serialize_settings_field(f) for f in manifest.settings.fields],
        "capabilities": [c.__name__ for c in manifest.capabilities],
        "webhooks": {
            "supported": manifest.webhooks.supported,
            "events": manifest.webhooks.events,
        },
    }


class ConnectionService:
    """Service layer for managing connector connections."""

    @staticmethod
    def get_adapter(connection) -> BasePort:
        """Instantiate the right adapter from a Connection model instance."""
        return registry.create_adapter(
            family=connection.provider_family,
            provider=connection.provider_name,
            credentials=connection.credentials,
            config=connection.config,
        )

    @staticmethod
    def test_connection(connection) -> ConnectionTestResult:
        """Test a connection and update its status."""
        adapter = ConnectionService.get_adapter(connection)
        result = adapter.test_connection()
        connection.is_connected = result.success
        connection.save(update_fields=["is_connected", "updated_at"])
        return result

    @staticmethod
    def rotate_credentials(connection, new_credentials: dict) -> None:
        """Update connection credentials (encrypted)."""
        connection.credentials = new_credentials
        connection.save(update_fields=["credentials_encrypted", "updated_at"])

    @staticmethod
    def validate_settings(connection, config: dict) -> list[str]:
        """Validate settings against the provider's manifest. Returns error messages."""
        manifest = registry.get_manifest(connection.provider_family, connection.provider_name)
        return manifest.settings.validate_settings(config)

    @staticmethod
    def update_settings(connection, config: dict) -> None:
        """Update connection settings (validated against manifest)."""
        errors = ConnectionService.validate_settings(connection, config)
        if errors:
            from bapp_connectors.core.errors import ConfigurationError

            raise ConfigurationError(f"Invalid settings: {'; '.join(errors)}")
        connection.config = config
        connection.save(update_fields=["config", "updated_at"])

    @staticmethod
    def validate_new_connection(model_class, provider_family: str, provider_name: str, tenant_filter: dict | None = None) -> list[str]:
        """Check whether a new connection for this provider is allowed.

        Args:
            model_class: The concrete Connection model class.
            provider_family: e.g. "shop", "payment".
            provider_name: e.g. "woocommerce", "stripe".
            tenant_filter: Extra queryset filter to scope uniqueness per tenant,
                e.g. ``{"company_id": 42}``.

        Returns:
            List of error messages (empty means OK to create).
        """
        manifest = registry.get_manifest(provider_family, provider_name)
        if manifest.allow_multiple:
            return []

        qs = model_class.objects.filter(
            provider_family=provider_family,
            provider_name=provider_name,
        )
        if tenant_filter:
            qs = qs.filter(**tenant_filter)

        if qs.exists():
            return [
                f"A {manifest.display_name} connection already exists. "
                f"This provider does not allow multiple connections."
            ]
        return []

    @staticmethod
    def list_available_providers(family: str | None = None):
        """List all registered provider manifests."""
        return registry.list_providers(family=family)

    @staticmethod
    def get_available_providers(
        family: str | None = None,
        family_meta: dict[str, dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        """Return a UI-ready dict of all available providers grouped by family.

        Ensures all provider packages are imported before querying the registry.

        Args:
            family: Optional filter — only include providers of this family
                (e.g. ``"shop"``).
            family_meta: Optional override for family display metadata.
                Merged on top of ``FAMILY_DEFAULTS``.  Keys are family values
                (e.g. ``"shop"``), values are dicts with ``label``, ``icon``,
                ``color``.

        Returns:
            ``{
                "families": [
                    {
                        "key": "shop",
                        "label": "E-commerce & Shops",
                        "icon": "fad fa-store",
                        "color": "#ec4899",
                        "providers": [
                            {
                                "name": "shopify",
                                "family": "shop",
                                "display_name": "Shopify",
                                "description": "...",
                                "allow_multiple": False,
                                "auth": {
                                    "strategy": "custom",
                                    "credential_fields": [...],
                                    "has_oauth": True,
                                    "oauth_display_name": "Connect with Shopify",
                                    "oauth_scopes": [...],
                                },
                                "settings": [...],
                                "capabilities": ["ShopPort", ...],
                                "webhooks": {"supported": True, "events": [...]},
                            },
                            ...
                        ]
                    },
                    ...
                ],
                "total_providers": 40,
            }``
        """
        ensure_providers_loaded()

        meta = {**FAMILY_DEFAULTS, **(family_meta or {})}
        manifests = registry.list_providers(family=family)

        # Group by family
        families: dict[str, dict[str, Any]] = {}
        for m in manifests:
            fam = m.family.value
            if fam not in families:
                fm = meta.get(fam, {"label": fam.replace("_", " ").title(), "icon": "fad fa-plug", "color": "#64748b"})
                families[fam] = {"key": fam, **fm, "providers": []}
            families[fam]["providers"].append(_serialize_provider(m))

        # Sort providers alphabetically within each family
        for fam_data in families.values():
            fam_data["providers"].sort(key=lambda p: p["display_name"])

        # Sort families by FAMILY_DEFAULTS order, unknown families at the end
        family_order = list(FAMILY_DEFAULTS.keys())
        sorted_families = sorted(
            families.values(),
            key=lambda f: family_order.index(f["key"]) if f["key"] in family_order else 99,
        )

        return {
            "families": sorted_families,
            "total_providers": len(manifests),
        }

    @staticmethod
    def get_provider_detail(family: str, provider: str) -> dict[str, Any]:
        """Return the full serialized manifest for a single provider.

        Ensures providers are loaded first.  Raises ``ConfigurationError``
        if the provider is not registered.
        """
        ensure_providers_loaded()
        manifest = registry.get_manifest(family, provider)
        return _serialize_provider(manifest)
