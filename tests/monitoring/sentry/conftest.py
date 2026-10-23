"""Fixture loaders for the anonymized Sentry REST captures.

Files are read lazily, so these loaders only fail when a test actually asks for one.
"""

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str):
    """Return the parsed JSON body of a captured Sentry response."""
    return json.loads((FIXTURES / f"{name}.json").read_text())


@pytest.fixture
def projects_raw():
    return load("projects")


@pytest.fixture
def project_raw():
    return load("project")


@pytest.fixture
def issues_raw():
    return load("issues")


@pytest.fixture
def issue_raw():
    return load("issue")


@pytest.fixture
def stats_v2_raw():
    return load("stats_v2")


@pytest.fixture
def hook_issue_created():
    return load("hook_issue_created")


@pytest.fixture
def hook_issue_resolved():
    return load("hook_issue_resolved")
