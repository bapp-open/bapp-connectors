"""Reusable contract tests every network provider must pass."""

import pytest

from bapp_connectors.core.dto import ConnectionTestResult, NetworkClient, NetworkDeviceInfo, NetworkSegment
from bapp_connectors.core.ports import NetworkPort


class NetworkContractTests:
    @pytest.fixture
    def adapter(self) -> NetworkPort:
        raise NotImplementedError("provider tests must supply an adapter fixture")

    def test_is_network_port(self, adapter):
        assert isinstance(adapter, NetworkPort)

    def test_validate_credentials(self, adapter):
        assert adapter.validate_credentials() is True

    def test_test_connection(self, adapter):
        result = adapter.test_connection()
        assert isinstance(result, ConnectionTestResult)
        assert result.success is True

    def test_get_device_info(self, adapter):
        info = adapter.get_device_info()
        assert isinstance(info, NetworkDeviceInfo)
        assert info.hostname

    def test_list_segments(self, adapter):
        segments = adapter.list_segments()
        assert isinstance(segments, list)
        assert all(isinstance(s, NetworkSegment) and s.ref for s in segments)

    def test_list_clients(self, adapter):
        clients = adapter.list_clients()
        assert isinstance(clients, list)
        assert all(isinstance(c, NetworkClient) and c.ip for c in clients)
