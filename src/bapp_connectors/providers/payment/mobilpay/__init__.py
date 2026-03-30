"""MobilPay (Netopia legacy) payment provider."""

from bapp_connectors.providers.payment.mobilpay.manifest import manifest

__all__ = ["MobilPayPaymentAdapter", "manifest"]

# Conditional registration — only if pyOpenSSL is installed
try:
    from OpenSSL import crypto  # noqa: F401

    from bapp_connectors.providers.payment.mobilpay.adapter import MobilPayPaymentAdapter
    from bapp_connectors.core.registry import registry
    registry.register(MobilPayPaymentAdapter)
except ImportError:
    pass
