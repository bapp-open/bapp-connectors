"""Stripe payment provider."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.payment.stripe.adapter import StripePaymentAdapter
from bapp_connectors.providers.payment.stripe.manifest import manifest

__all__ = ["StripePaymentAdapter", "manifest"]

# Auto-register with the global registry
registry.register(StripePaymentAdapter)
