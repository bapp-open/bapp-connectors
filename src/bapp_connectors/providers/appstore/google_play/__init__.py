"""Google Play provider (cere extra-ul `appstore`: PyJWT[crypto])."""

from bapp_connectors.providers.appstore.google_play.adapter import GooglePlayAdapter
from bapp_connectors.providers.appstore.google_play.manifest import manifest

__all__ = ["GooglePlayAdapter", "manifest"]

try:
    import jwt  # noqa: F401

    from bapp_connectors.core.registry import registry

    registry.register(GooglePlayAdapter)
except ImportError:
    pass
