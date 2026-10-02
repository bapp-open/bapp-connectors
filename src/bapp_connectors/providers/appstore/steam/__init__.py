"""Steam provider (Steamworks partner API) — fara dependente optionale."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.appstore.steam.adapter import SteamAdapter
from bapp_connectors.providers.appstore.steam.manifest import manifest

__all__ = ["SteamAdapter", "manifest"]

registry.register(SteamAdapter)
