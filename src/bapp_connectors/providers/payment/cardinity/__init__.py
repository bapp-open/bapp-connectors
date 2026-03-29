"""Cardinity payment provider."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.payment.cardinity.adapter import CardinityPaymentAdapter
from bapp_connectors.providers.payment.cardinity.manifest import manifest

__all__ = ["CardinityPaymentAdapter", "manifest"]

registry.register(CardinityPaymentAdapter)
