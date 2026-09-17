"""Reusable contract tests every hosting provider must pass."""

import pytest

from bapp_connectors.core.dto import ConnectionTestResult, HostingAccount, HostingDomain, HostingResource
from bapp_connectors.core.ports import HostingPort


class HostingContractTests:
    @pytest.fixture
    def adapter(self) -> HostingPort:
        raise NotImplementedError("provider tests must supply an adapter fixture")

    def test_is_hosting_port(self, adapter):
        assert isinstance(adapter, HostingPort)

    def test_validate_credentials(self, adapter):
        assert adapter.validate_credentials() is True

    def test_test_connection(self, adapter):
        result = adapter.test_connection()
        assert isinstance(result, ConnectionTestResult)
        assert result.success is True

    def test_get_account(self, adapter):
        account = adapter.get_account()
        assert isinstance(account, HostingAccount)
        assert account.username

    def test_get_usage(self, adapter):
        usage = adapter.get_usage()
        assert isinstance(usage, list)
        assert all(isinstance(r, HostingResource) and r.key for r in usage)

    def test_list_domains(self, adapter):
        domains = adapter.list_domains()
        assert isinstance(domains, list)
        assert all(isinstance(d, HostingDomain) and d.domain and d.kind for d in domains)
