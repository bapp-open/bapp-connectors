"""Conversions between raw UAPI payloads and framework DTOs."""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from bapp_connectors.core.dto import (
    DnsRecord,
    DnsZoneSnapshot,
    HostingAccount,
    HostingDomain,
    HostingResource,
    Mailbox,
)
from bapp_connectors.providers.hosting.cpanel.models import CpanelPop, CpanelZoneLine

_DOMAIN_KINDS = {
    "main_domain": "main",
    "addon_domains": "addon",
    "parked_domains": "parked",
    "sub_domains": "sub",
}


def _decimal(value: Any) -> Decimal | None:
    """Parse a UAPI numeric that may be a string, a number, None, or 'unlimited'."""
    if value is None or value == "" or str(value).lower() == "unlimited":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def map_usages(raw: list[dict]) -> list[HostingResource]:
    """`ResourceUsage/get_usages` to normalized resources.

    `maximum: null` means unlimited and must stay None — mapping it to 0 turns an
    unlimited resource into a full one.
    """
    resources = []
    for item in raw or []:
        used = _decimal(item.get("usage"))
        limit = _decimal(item.get("maximum"))
        percent = None
        if used is not None and limit is not None and limit > 0:
            percent = float(used / limit * 100)
        resources.append(
            HostingResource(
                key=str(item.get("id", "")),
                label=str(item.get("description") or ""),
                used=used,
                limit=limit,
                unit="bytes" if item.get("formatter") == "format_bytes" else "count",
                percent=percent,
            )
        )
    return resources


def _cert_index(certs: list[dict]) -> dict[str, dict]:
    """Map every FQDN a certificate covers to that certificate."""
    index: dict[str, dict] = {}
    for host in certs or []:
        certificate = host.get("certificate") or {}
        names = set(host.get("fqdns") or []) | set(host.get("domains") or []) | set(certificate.get("domains") or [])
        for name in names:
            index.setdefault(name, certificate)
    return index


def map_domains(raw: dict, certs: list[dict]) -> list[HostingDomain]:
    """`DomainInfo/domains_data` plus `SSL/installed_hosts` to domains with SSL state."""
    index = _cert_index(certs)
    domains: list[HostingDomain] = []

    for key, kind in _DOMAIN_KINDS.items():
        entries = raw.get(key) or []
        if isinstance(entries, dict):  # main_domain is a single object
            entries = [entries]
        for entry in entries:
            if isinstance(entry, str):  # some panels return bare names
                entry = {"domain": entry}
            name = entry.get("domain") or entry.get("servername") or ""
            certificate = index.get(name) or {}
            not_after = certificate.get("not_after")
            domains.append(
                HostingDomain(
                    domain=name,
                    kind=kind,
                    document_root=entry.get("documentroot") or "",
                    parent_domain=entry.get("parent_domain") or "",
                    ssl_expires_at=datetime.fromtimestamp(int(not_after), tz=UTC) if not_after else None,
                    ssl_issuer=str(certificate.get("issuer.organizationName") or ""),
                    ssl_auto=bool(int(certificate.get("is_autossl") or 0)),
                    extra={"ip": entry.get("ip", ""), "serveralias": entry.get("serveralias", "")},
                )
            )
    return domains


def map_account(user_info: dict, hostname: str, primary_domain: str) -> HostingAccount:
    """`Variables/get_user_information` to the account identity."""
    return HostingAccount(
        username=str(user_info.get("user") or ""),
        primary_domain=primary_domain,
        plan=str(user_info.get("plan") or ""),
        server_hostname=hostname,
        panel_version=str(user_info.get("cpanel_version") or ""),
        extra={"maximum_mail_accounts": user_info.get("maximum_mail_accounts")},
    )


def map_mailboxes(raw: list[dict]) -> list[Mailbox]:
    """`Email/list_pops_with_disk` to mailboxes, in bytes."""
    boxes = []
    for item in raw or []:
        pop = CpanelPop.model_validate(item)
        boxes.append(
            Mailbox(
                email=pop.email,
                login=pop.login or pop.email,
                domain=pop.domain,
                disk_used=_decimal(pop.raw_disk_used),
                disk_quota=_decimal(pop.raw_disk_quota),
                percent_used=pop.diskusedpercent_float,
                suspended_login=bool(pop.suspended_login),
                suspended_incoming=bool(pop.suspended_incoming),
            )
        )
    return boxes


def _b64(value: str | None) -> str:
    if not value:
        return ""
    return base64.b64decode(value).decode("utf-8", errors="replace")


# Record types whose leading positional fields are numbers rather than part of the value.
_LEADING_NUMBERS = {"MX": ("priority",), "SRV": ("priority", "weight", "port"), "CAA": ("flags",)}

# SOA and NS are readable but `mass_edit_zone` refuses to write them, so they are
# not offered as editable records.
_NOT_EDITABLE = {"SOA", "NS"}


def map_zone(zone: str, raw_lines: list[dict]) -> DnsZoneSnapshot:
    """`DNS/parse_zone` to a snapshot. The SOA serial becomes the write token."""
    version = ""
    records: list[DnsRecord] = []

    for item in raw_lines or []:
        line = CpanelZoneLine.model_validate(item)
        if line.type != "record" or not line.record_type:
            continue

        fields = [_b64(chunk) for chunk in (line.data_b64 or [])]

        if line.record_type == "SOA":
            # SOA data is: primary, hostmaster, serial, refresh, retry, expire, minimum
            if len(fields) >= 3:
                version = fields[2]
            continue
        if line.record_type in _NOT_EDITABLE:
            continue

        priority = None
        extra: dict = {}
        leading = _LEADING_NUMBERS.get(line.record_type, ())
        if leading and len(fields) > len(leading):
            for name, raw_value in zip(leading, fields, strict=False):
                try:
                    parsed = int(raw_value)
                except ValueError:
                    parsed = raw_value
                if name == "priority":
                    priority = parsed
                else:
                    extra[name] = parsed
            fields = fields[len(leading) :]

        records.append(
            DnsRecord(
                ref=str(line.line_index),
                name=_b64(line.dname_b64) or (line.dname_raw or ""),
                record_type=line.record_type,
                ttl=line.ttl or 0,
                value=" ".join(fields),
                priority=priority,
                extra=extra,
            )
        )

    return DnsZoneSnapshot(zone=zone, version=version, records=records)


def record_to_payload(record: DnsRecord, include_ref: bool = False) -> dict:
    """A `DnsRecord` to the object `mass_edit_zone` expects.

    `data` is always an array — the server rejects a scalar outright.
    """
    data: list[str] = []
    if record.priority is not None:
        data.append(str(record.priority))
    if record.record_type == "SRV":
        data.append(str(record.extra.get("weight", 0)))
        data.append(str(record.extra.get("port", 0)))
    data.extend(part for part in record.value.split(" ") if part)

    payload: dict = {
        "dname": record.name,
        "ttl": record.ttl,
        "record_type": record.record_type,
        "data": data,
    }
    if include_ref:
        payload["line_index"] = int(record.ref)
    return payload
