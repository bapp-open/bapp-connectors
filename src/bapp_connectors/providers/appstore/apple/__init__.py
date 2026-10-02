"""Apple App Store provider (cere extra-ul `appstore`: PyJWT[crypto])."""

from bapp_connectors.providers.appstore.apple.adapter import AppleAppStoreAdapter
from bapp_connectors.providers.appstore.apple.manifest import manifest

__all__ = ["AppleAppStoreAdapter", "manifest"]

# Inregistrare conditionata — doar daca PyJWT (cu cryptography) e instalat
try:
    import jwt  # noqa: F401

    from bapp_connectors.core.registry import registry
    registry.register(AppleAppStoreAdapter)
except ImportError:
    pass
