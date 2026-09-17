"""Fixture loader for the anonymized UAPI captures."""

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str):
    """Return the `data` payload of a captured UAPI envelope."""
    return json.loads((FIXTURES / f"{name}.json").read_text())["data"]


@pytest.fixture
def usages_raw():
    return load("usages")


@pytest.fixture
def domains_raw():
    return load("domains_data")


@pytest.fixture
def ssl_raw():
    return load("ssl_hosts")


@pytest.fixture
def pops_raw():
    return load("pops_disk")


@pytest.fixture
def zone_raw():
    return load("zone")
