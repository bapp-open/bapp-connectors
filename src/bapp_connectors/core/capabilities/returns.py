"""Returns capability -- read-only access to returns / refunds of a shop or marketplace."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from bapp_connectors.core.dto import ShopReturn


class ReturnsCapability(ABC):
    """Adapter can list the returns (or refunds) created in a time window. Never writes."""

    @abstractmethod
    def get_returns(self, since: datetime, until: datetime) -> list[ShopReturn]:
        """Returns requested/changed between `since` and `until` (aware datetimes)."""
        ...

    def resolve_return_awb(self, awb_ref: str) -> str:
        """Turn `ShopReturn.awb_ref` into a printable AWB number; "" when unknown."""
        return ""
