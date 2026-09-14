"""DNS allowlist capability — restrict a segment's clients to an explicit list of domains."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bapp_connectors.core.dto import DetectedDnsAllowlist, DnsAllowlist


class DnsAllowlistCapability(ABC):
    """Adapter can read and replace the DNS allowlist of a network segment.

    `config` carries the provider-specific location of the list for that segment
    (for pfSense: `{"view": "elevi", "cidr": "172.16.196.0/22"}`). The adapter never
    touches configuration outside the block it owns.
    """

    @abstractmethod
    def get_dns_allowlist(self, segment_ref: str, config: dict) -> DnsAllowlist:
        """Read the current allowlist; `present=False` when none is configured."""
        ...

    @abstractmethod
    def set_dns_allowlist(self, segment_ref: str, config: dict, domains: list[str]) -> DnsAllowlist:
        """Replace the allowlist with `domains`, persist it, apply it, and return the re-read list."""
        ...

    def detect_dns_allowlists(self) -> list[DetectedDnsAllowlist]:
        """Allowlists already configured on the device, one per segment, with the `config`
        that `get_dns_allowlist`/`set_dns_allowlist` expect for it. Optional: default none."""
        return []
