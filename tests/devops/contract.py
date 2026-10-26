"""Reusable contract tests every DevOps provider must pass."""

import pytest

from bapp_connectors.core.dto import ConnectionTestResult, Issue, PaginatedResult, Pipeline, Repository
from bapp_connectors.core.ports import DevOpsPort


class DevOpsContractTests:
    """Subclass and override `adapter` (and `project_ref` when the canned data needs another ref)."""

    project_ref = "1"

    @pytest.fixture
    def adapter(self) -> DevOpsPort:
        raise NotImplementedError("provider tests must supply an adapter fixture")

    def test_is_devops_port(self, adapter):
        assert isinstance(adapter, DevOpsPort)

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
        assert all(isinstance(r, Repository) and r.ref and r.full_path for r in result.items)

    def test_get_project(self, adapter):
        repo = adapter.get_project(self.project_ref)
        assert isinstance(repo, Repository)
        assert repo.ref and repo.full_path

    def test_list_issues(self, adapter):
        result = adapter.list_issues(self.project_ref)
        assert isinstance(result, PaginatedResult)
        assert all(isinstance(i, Issue) and i.number for i in result.items)

    def test_list_pipelines(self, adapter):
        result = adapter.list_pipelines(self.project_ref)
        assert isinstance(result, PaginatedResult)
        assert all(isinstance(p, Pipeline) and p.ref for p in result.items)
