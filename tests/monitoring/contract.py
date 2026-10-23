"""Reusable contract tests every monitoring provider must pass."""

import pytest

from bapp_connectors.core.dto import ConnectionTestResult, PaginatedResult
from bapp_connectors.core.dto.monitoring import ErrorIssue, MonitoredProject, MonitoredProjectStats
from bapp_connectors.core.ports import MonitoringPort


class MonitoringContractTests:
    """Subclass and override `adapter` (and `project_ref` when the canned data needs another ref).

    The canned data must hold at least one project, one issue and some events, so the
    list assertions below are never vacuous.
    """

    project_ref = "1"

    @pytest.fixture
    def adapter(self) -> MonitoringPort:
        raise NotImplementedError("provider tests must supply an adapter fixture")

    def test_is_monitoring_port(self, adapter):
        assert isinstance(adapter, MonitoringPort)

    def test_validate_credentials(self, adapter):
        assert adapter.validate_credentials() is True

    def test_test_connection(self, adapter):
        result = adapter.test_connection()
        assert isinstance(result, ConnectionTestResult)
        assert result.success is True

    def test_list_projects(self, adapter):
        result = adapter.list_projects()
        assert isinstance(result, PaginatedResult)
        assert result.items
        assert all(isinstance(p, MonitoredProject) and p.ref and p.slug for p in result.items)

    def test_list_issues(self, adapter):
        result = adapter.list_issues(self.project_ref)
        assert isinstance(result, PaginatedResult)
        assert result.items
        assert all(isinstance(i, ErrorIssue) and i.id and i.short_id for i in result.items)
        assert all(i.ref == self.project_ref for i in result.items)

    def test_get_project_stats(self, adapter):
        stats = adapter.get_project_stats(self.project_ref)
        assert isinstance(stats, MonitoredProjectStats)
        assert stats.ref == self.project_ref and stats.period
        assert stats.errors_received > 0
        assert stats.events + stats.errors_rejected == stats.errors_received
