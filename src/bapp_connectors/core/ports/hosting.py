"""Hosting port — a shared-hosting control-panel account."""

from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING

from bapp_connectors.core.ports.base import BasePort

if TYPE_CHECKING:
    from bapp_connectors.core.dto import HostingAccount, HostingDomain, HostingResource


class HostingPort(BasePort):
    """Base operations every hosting control-panel provider must implement.

    Mailbox management and panel links are optional capabilities, not port
    methods: a provider may run a panel with no mail service at all.
    """

    @abstractmethod
    def get_account(self) -> HostingAccount:
        """Identity of the account: user, primary domain, plan, server."""
        ...

    @abstractmethod
    def get_usage(self) -> list[HostingResource]:
        """Every metered resource the panel reports, normalized."""
        ...

    @abstractmethod
    def list_domains(self) -> list[HostingDomain]:
        """Main, addon, parked and sub domains, with SSL state where known."""
        ...
