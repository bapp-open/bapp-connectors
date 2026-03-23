"""
Configurable order status mapping.

Each provider has a default status mapping (hardcoded in its mappers).
Tenants can override these via connection config settings:

    config = {
        "status_map_inbound": {"wc-shipped": "shipped", "processing": "processing"},
        "status_map_outbound": {"shipped": "wc-shipped", "delivered": "completed"},
    }

The StatusMapper class merges tenant overrides on top of the provider defaults.
"""

from __future__ import annotations

from bapp_connectors.core.dto import OrderStatus


class StatusMapper:
    """
    Bidirectional order status mapper with tenant-configurable overrides.

    Args:
        default_inbound: Provider's default mapping {raw_status: OrderStatus}.
        default_outbound: Provider's default mapping {OrderStatus: raw_status}.
        config_inbound: Tenant overrides {raw_status: framework_status_string}.
        config_outbound: Tenant overrides {framework_status_string: raw_status}.
    """

    def __init__(
        self,
        default_inbound: dict[str, OrderStatus],
        default_outbound: dict[OrderStatus, str],
        config_inbound: dict[str, str] | None = None,
        config_outbound: dict[str, str] | None = None,
    ):
        # Build inbound map: start with defaults, override with tenant config
        self._inbound: dict[str, OrderStatus] = dict(default_inbound)
        if config_inbound:
            for raw, framework_str in config_inbound.items():
                try:
                    self._inbound[raw] = OrderStatus(framework_str)
                except ValueError:
                    pass  # skip invalid status strings

        # Build outbound map: start with defaults, override with tenant config
        self._outbound: dict[OrderStatus, str] = dict(default_outbound)
        if config_outbound:
            for framework_str, raw in config_outbound.items():
                try:
                    self._outbound[OrderStatus(framework_str)] = raw
                except ValueError:
                    pass

    def to_framework(self, raw_status: str, default: OrderStatus = OrderStatus.PENDING) -> OrderStatus:
        """Map a provider's raw status to a framework OrderStatus."""
        return self._inbound.get(raw_status, default)

    def to_provider(self, status: OrderStatus) -> str | None:
        """Map a framework OrderStatus to the provider's raw status. Returns None if unmapped."""
        return self._outbound.get(status)

    @classmethod
    def from_config(
        cls,
        default_inbound: dict[str, OrderStatus],
        default_outbound: dict[OrderStatus, str],
        config: dict | None = None,
    ) -> StatusMapper:
        """Create a StatusMapper from adapter config dict.

        Reads `status_map_inbound` and `status_map_outbound` from config.
        """
        config = config or {}
        return cls(
            default_inbound=default_inbound,
            default_outbound=default_outbound,
            config_inbound=config.get("status_map_inbound"),
            config_outbound=config.get("status_map_outbound"),
        )
