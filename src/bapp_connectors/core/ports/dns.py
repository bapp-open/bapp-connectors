"""DNS port — authoritative zone management, shared by hosting panels and DNS providers."""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Sequence
from typing import TYPE_CHECKING

from bapp_connectors.core.ports.base import BasePort

if TYPE_CHECKING:
    from bapp_connectors.core.dto import DnsRecord, DnsZone, DnsZoneSnapshot


class DnsPort(BasePort):
    """Contract for authoritative DNS zone management."""

    supported_record_types: tuple[str, ...] = ()
    """Record types this provider can WRITE. A UI offers only these."""

    @abstractmethod
    def list_zones(self) -> list[DnsZone]:
        """Zones this connection is authoritative for."""
        ...

    @abstractmethod
    def get_zone(self, zone: str) -> DnsZoneSnapshot:
        """Full snapshot. `version` and each record's `ref` are opaque round-trip tokens."""
        ...

    @abstractmethod
    def apply_changes(
        self,
        zone: str,
        version: str,
        *,
        add: Sequence[DnsRecord] = (),
        edit: Sequence[DnsRecord] = (),
        remove: Sequence[str] = (),
    ) -> DnsZoneSnapshot:
        """Apply changes and return the re-read zone.

        `version` is the value from the snapshot the edits were based on. Providers
        with optimistic concurrency MUST reject a stale version rather than
        overwrite; providers without it ignore the argument.

        `add` entries carry no `ref`; `edit` entries carry the `ref` they were read
        with; `remove` is a list of `ref`s.
        """
        ...
