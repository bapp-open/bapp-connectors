"""
Invoice attachment capability — optional interface for attaching invoices to orders.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class InvoiceAttachmentCapability(ABC):
    """Adapter supports attaching invoices to orders on the marketplace."""

    @abstractmethod
    def attach_invoice(self, order_id: str, invoice_url: str) -> bool:
        """Attach an invoice URL to an order. Returns True if successful."""
        ...
