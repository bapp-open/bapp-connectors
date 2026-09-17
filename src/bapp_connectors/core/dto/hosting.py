"""Hosting family DTOs — control-panel account, resources, domains, mailboxes, links."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from bapp_connectors.core.dto.base import BaseDTO


class HostingAccount(BaseDTO):
    """Identity of a shared-hosting control-panel account."""

    username: str
    primary_domain: str
    plan: str = ""
    server_hostname: str = ""
    panel_version: str = ""
    extra: dict = {}


class HostingResource(BaseDTO):
    """One metered resource reported by the panel: disk, bandwidth, mailbox count, ..."""

    key: str
    label: str = ""
    used: Decimal | None = None
    limit: Decimal | None = None
    """None means unlimited. Never use 0 to mean unlimited."""
    unit: str = ""
    """bytes | count"""
    percent: float | None = None


class HostingDomain(BaseDTO):
    """A domain served by the account, with its SSL state."""

    domain: str
    kind: str
    """main | addon | parked | sub"""
    document_root: str = ""
    parent_domain: str = ""
    ssl_expires_at: datetime | None = None
    ssl_issuer: str = ""
    ssl_auto: bool = False
    extra: dict = {}


class Mailbox(BaseDTO):
    """An email account on the hosting plan. Disk figures are bytes."""

    email: str
    login: str
    domain: str
    disk_used: Decimal | None = None
    disk_quota: Decimal | None = None
    """None means unlimited."""
    percent_used: float | None = None
    suspended_login: bool = False
    suspended_incoming: bool = False
    extra: dict = {}


class PanelLink(BaseDTO):
    """A URL that opens the panel or webmail."""

    url: str
    kind: str
    """panel | webmail"""
    single_sign_on: bool
    """False means the user still has to log in at the far end."""
    expires_at: datetime | None = None
