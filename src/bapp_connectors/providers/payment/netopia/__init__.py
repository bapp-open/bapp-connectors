"""Netopia payment provider."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.payment.netopia.adapter import NetopiaPaymentAdapter
from bapp_connectors.providers.payment.netopia.manifest import manifest

__all__ = ["NetopiaPaymentAdapter", "manifest"]

# Auto-register with the global registry
registry.register(NetopiaPaymentAdapter)
