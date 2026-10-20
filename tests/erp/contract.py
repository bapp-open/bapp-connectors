"""Reusable contract tests every ERP provider must pass."""

import pytest

from bapp_connectors.core.ports import BasePort, ErpPort


class ErpContractTests:
    @pytest.fixture
    def erp_adapter(self) -> ErpPort:
        raise NotImplementedError("provider tests must supply an erp_adapter fixture")

    def test_is_erp_port(self, erp_adapter):
        assert isinstance(erp_adapter, ErpPort)
        assert isinstance(erp_adapter, BasePort)

    def test_validate_credentials(self, erp_adapter):
        assert erp_adapter.validate_credentials() is True

    def test_capabilities_shape(self, erp_adapter):
        caps = erp_adapter.get_capabilities()
        assert isinstance(caps["print"], bool)
        assert isinstance(caps["sms"], bool)
        assert isinstance(caps["devices"], list)
        assert isinstance(caps["phones"], list)

    def test_print_file_returns_dict(self, erp_adapter):
        assert isinstance(erp_adapter.print_file("https://example.test/a.pdf"), dict)

    def test_send_sms_returns_dict(self, erp_adapter):
        assert isinstance(erp_adapter.send_sms(["+40700000000"], "hi"), dict)

    def test_test_connection(self, erp_adapter):
        assert erp_adapter.test_connection().success is True
