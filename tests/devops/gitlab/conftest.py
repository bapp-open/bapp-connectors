"""Fixture loaders for the anonymized GitLab REST captures.

Files are read lazily, so these loaders only fail when a test actually asks for one.
"""

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str):
    """Return the parsed JSON body of a captured GitLab response."""
    return json.loads((FIXTURES / f"{name}.json").read_text())


@pytest.fixture
def projects_raw():
    return load("projects")


@pytest.fixture
def issues_raw():
    return load("issues")


@pytest.fixture
def merge_requests_raw():
    return load("merge_requests")


@pytest.fixture
def commits_raw():
    return load("commits")


@pytest.fixture
def pipelines_raw():
    return load("pipelines")


@pytest.fixture
def user_raw():
    return load("user")


@pytest.fixture
def project_raw():
    return load("project")


@pytest.fixture
def hook_push():
    return load("hook_push")


@pytest.fixture
def hook_issue():
    return load("hook_issue")


@pytest.fixture
def hook_merge_request():
    return load("hook_merge_request")


@pytest.fixture
def hook_pipeline():
    return load("hook_pipeline")


@pytest.fixture
def hook_note():
    return load("hook_note")
