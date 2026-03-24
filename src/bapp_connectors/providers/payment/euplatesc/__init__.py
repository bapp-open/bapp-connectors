"""EuPlatesc Romanian payment gateway provider."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.payment.euplatesc.adapter import EuPlatescPaymentAdapter
from bapp_connectors.providers.payment.euplatesc.manifest import manifest

__all__ = ["EuPlatescPaymentAdapter", "manifest"]

registry.register(EuPlatescPaymentAdapter)
