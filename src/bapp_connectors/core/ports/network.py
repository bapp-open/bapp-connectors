"""Network port — read-only view of a managed router/firewall."""

from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING

from bapp_connectors.core.ports.base import BasePort

if TYPE_CHECKING:
    from bapp_connectors.core.dto import NetworkClient, NetworkDeviceInfo, NetworkSegment


class NetworkPort(BasePort):
    """Base operations every network device provider must implement."""

    @abstractmethod
    def get_device_info(self) -> NetworkDeviceInfo:
        """Hostname, model and firmware version of the device."""
        ...

    @abstractmethod
    def list_segments(self) -> list[NetworkSegment]:
        """Configured network segments (interfaces/VLANs) that carry an address."""
        ...

    @abstractmethod
    def list_clients(self, segment_ref: str | None = None) -> list[NetworkClient]:
        """Clients currently known to the device, optionally restricted to one segment."""
        ...
