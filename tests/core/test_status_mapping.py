"""Tests for configurable order status mapping."""

from bapp_connectors.core.dto import OrderStatus
from bapp_connectors.core.status_mapping import StatusMapper


DEFAULT_INBOUND = {
    "pending": OrderStatus.PENDING,
    "processing": OrderStatus.PROCESSING,
    "completed": OrderStatus.DELIVERED,
    "cancelled": OrderStatus.CANCELLED,
}

DEFAULT_OUTBOUND = {
    OrderStatus.PENDING: "pending",
    OrderStatus.PROCESSING: "processing",
    OrderStatus.DELIVERED: "completed",
    OrderStatus.CANCELLED: "cancelled",
}


class TestInbound:

    def test_default_mapping(self):
        mapper = StatusMapper(DEFAULT_INBOUND, DEFAULT_OUTBOUND)
        assert mapper.to_framework("completed") == OrderStatus.DELIVERED

    def test_unknown_status_returns_default(self):
        mapper = StatusMapper(DEFAULT_INBOUND, DEFAULT_OUTBOUND)
        assert mapper.to_framework("wc-custom") == OrderStatus.PENDING

    def test_tenant_override(self):
        mapper = StatusMapper(
            DEFAULT_INBOUND, DEFAULT_OUTBOUND,
            config_inbound={"wc-shipped": "shipped"},
        )
        assert mapper.to_framework("wc-shipped") == OrderStatus.SHIPPED

    def test_tenant_override_replaces_default(self):
        mapper = StatusMapper(
            DEFAULT_INBOUND, DEFAULT_OUTBOUND,
            config_inbound={"processing": "shipped"},
        )
        # "processing" was PROCESSING by default, now overridden to SHIPPED
        assert mapper.to_framework("processing") == OrderStatus.SHIPPED

    def test_invalid_tenant_status_ignored(self):
        mapper = StatusMapper(
            DEFAULT_INBOUND, DEFAULT_OUTBOUND,
            config_inbound={"wc-custom": "nonexistent_status"},
        )
        # Invalid config value silently skipped
        assert mapper.to_framework("wc-custom") == OrderStatus.PENDING


class TestOutbound:

    def test_default_mapping(self):
        mapper = StatusMapper(DEFAULT_INBOUND, DEFAULT_OUTBOUND)
        assert mapper.to_provider(OrderStatus.DELIVERED) == "completed"

    def test_unmapped_returns_none(self):
        mapper = StatusMapper(DEFAULT_INBOUND, DEFAULT_OUTBOUND)
        assert mapper.to_provider(OrderStatus.REFUNDED) is None

    def test_tenant_override(self):
        mapper = StatusMapper(
            DEFAULT_INBOUND, DEFAULT_OUTBOUND,
            config_outbound={"shipped": "wc-shipped"},
        )
        assert mapper.to_provider(OrderStatus.SHIPPED) == "wc-shipped"

    def test_tenant_override_replaces_default(self):
        mapper = StatusMapper(
            DEFAULT_INBOUND, DEFAULT_OUTBOUND,
            config_outbound={"delivered": "wc-delivered-custom"},
        )
        assert mapper.to_provider(OrderStatus.DELIVERED) == "wc-delivered-custom"


class TestFromConfig:

    def test_empty_config(self):
        mapper = StatusMapper.from_config(DEFAULT_INBOUND, DEFAULT_OUTBOUND)
        assert mapper.to_framework("completed") == OrderStatus.DELIVERED
        assert mapper.to_provider(OrderStatus.PENDING) == "pending"

    def test_with_config_overrides(self):
        config = {
            "status_map_inbound": {"wc-ready": "processing", "wc-shipped": "shipped"},
            "status_map_outbound": {"shipped": "wc-shipped"},
        }
        mapper = StatusMapper.from_config(DEFAULT_INBOUND, DEFAULT_OUTBOUND, config)

        assert mapper.to_framework("wc-ready") == OrderStatus.PROCESSING
        assert mapper.to_framework("wc-shipped") == OrderStatus.SHIPPED
        assert mapper.to_provider(OrderStatus.SHIPPED) == "wc-shipped"
        # Defaults still work
        assert mapper.to_framework("completed") == OrderStatus.DELIVERED

    def test_none_config(self):
        mapper = StatusMapper.from_config(DEFAULT_INBOUND, DEFAULT_OUTBOUND, None)
        assert mapper.to_framework("pending") == OrderStatus.PENDING
