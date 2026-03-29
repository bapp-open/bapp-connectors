"""PayPal payment provider."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.payment.paypal.adapter import PayPalPaymentAdapter
from bapp_connectors.providers.payment.paypal.manifest import manifest

__all__ = ["PayPalPaymentAdapter", "manifest"]

registry.register(PayPalPaymentAdapter)
