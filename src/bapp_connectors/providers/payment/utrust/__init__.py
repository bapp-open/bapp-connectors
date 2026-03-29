"""Utrust payment provider."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.payment.utrust.adapter import UtrustPaymentAdapter
from bapp_connectors.providers.payment.utrust.manifest import manifest

__all__ = ["UtrustPaymentAdapter", "manifest"]

registry.register(UtrustPaymentAdapter)
