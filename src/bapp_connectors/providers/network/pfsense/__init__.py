"""pfSense network provider (XML-RPC exec_php)."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.network.pfsense.adapter import PfSenseNetworkAdapter
from bapp_connectors.providers.network.pfsense.manifest import manifest

__all__ = ["PfSenseNetworkAdapter", "manifest"]

# Auto-register with the global registry
registry.register(PfSenseNetworkAdapter)
