"""Conversions between raw UAPI payloads and framework DTOs."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from bapp_connectors.core.dto import HostingAccount, HostingDomain, HostingResource

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
