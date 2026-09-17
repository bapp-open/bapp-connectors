"""DNS family DTOs — zones, records, and a snapshot that carries a write token.

`DnsRecord.ref` and `DnsZoneSnapshot.version` are OPAQUE to callers. They come out
of `get_zone` and go back into `apply_changes` untouched. cPanel encodes a line
index and the SOA serial in them; Cloudflare encodes a record id and nothing.
"""

from __future__ import annotations

from bapp_connectors.core.dto.base import BaseDTO


class DnsZone(BaseDTO):
    """A zone the account is authoritative for."""

    zone: str
    editable: bool = True
    extra: dict = {}


class DnsRecord(BaseDTO):
    """One resource record."""

    ref: str = ""
    """Opaque provider handle. Empty when creating — `add` ignores it."""
    name: str
    record_type: str
    ttl: int
    value: str
    """Rendered, human-editable form of the record's data."""
    priority: int | None = None
    extra: dict = {}
    """Provider-only data, e.g. Cloudflare's `proxied`, SRV weight and port."""


class DnsZoneSnapshot(BaseDTO):
    """A zone as read at one instant, with the token needed to write it back."""

    zone: str
    version: str = ""
    """Opaque concurrency token. Empty for providers without optimistic locking."""
    records: list[DnsRecord] = []
