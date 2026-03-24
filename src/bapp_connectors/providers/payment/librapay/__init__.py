"""LibraPay payment gateway provider."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.payment.librapay.adapter import LibraPayPaymentAdapter
from bapp_connectors.providers.payment.librapay.manifest import manifest

__all__ = ["LibraPayPaymentAdapter", "manifest"]

registry.register(LibraPayPaymentAdapter)
