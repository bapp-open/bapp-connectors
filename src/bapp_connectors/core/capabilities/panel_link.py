"""Panel link capability — URLs that open the provider's own UI."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bapp_connectors.core.dto import PanelLink


class PanelLinkCapability(ABC):
    """Adapter can hand out links into the provider's web UI.

    `PanelLink.single_sign_on` says whether the link logs the user in. A provider
    that can only offer a login page returns False, and the caller must not present
    the link as one-click.
    """

    @abstractmethod
    def get_panel_link(self) -> PanelLink:
        """Link to the control panel itself."""
        ...

    @abstractmethod
    def get_webmail_link(self, email: str | None = None) -> PanelLink:
        """Link to webmail; for a specific mailbox when `email` is given."""
        ...
