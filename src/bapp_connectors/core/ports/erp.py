"""ERP port — run print and SMS actions through a business ERP."""

from __future__ import annotations

from abc import abstractmethod

from bapp_connectors.core.ports.base import BasePort


class ErpPort(BasePort):
    """Contract for an ERP that can print files and send SMS through its own devices."""

    @abstractmethod
    def get_capabilities(self) -> dict:
        """What this ERP connection can do.

        Returns ``{'print': bool, 'sms': bool, 'devices': [{'id', 'alias', 'printers',
        'default_printer', 'last_active'}], 'phones': [{'id', 'label'}]}``.
        """
        ...

    @abstractmethod
    def print_file(self, url: str, device: str = "", printer: str = "", copies: int = 1) -> dict:
        """Print the file at ``url``. Returns ``{'device', 'device_alias', 'printer'}``."""
        ...

    @abstractmethod
    def send_sms(self, recipients: list[str], body: str, phone: str = "") -> dict:
        """Send an SMS to ``recipients`` from ``phone`` (default phone when empty). Returns ``{'phone', 'count'}``."""
        ...
