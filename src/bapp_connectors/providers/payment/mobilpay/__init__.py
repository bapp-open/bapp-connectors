"""MobilPay (Netopia legacy) payment provider."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.payment.mobilpay.adapter import MobilPayPaymentAdapter
from bapp_connectors.providers.payment.mobilpay.manifest import manifest

__all__ = ["MobilPayPaymentAdapter", "manifest"]

registry.register(MobilPayPaymentAdapter)
