"""
SFTP storage integration tests — runs against atmoz/sftp in Docker.

Requires:
    docker compose -f docker-compose.test.yml up -d
    uv run --extra dev --extra sftp pytest tests/storage/test_sftp.py -v -m integration
"""

from __future__ import annotations

import pytest

from tests.storage.conftest import SFTP_HOST, SFTP_PORT, skip_unless_sftp

pytestmark = [pytest.mark.integration, skip_unless_sftp]


@pytest.fixture
def adapter():
    from bapp_connectors.providers.storage.sftp.adapter import SFTPStorageAdapter

    return SFTPStorageAdapter(
        credentials={
            "host": SFTP_HOST,
            "username": "testuser",
            "password": "testpass",
        },
        config={
            "port": SFTP_PORT,
            "default_folder": "/upload",
        },
    )


class TestSFTPContract:
    """Run the full storage contract suite against SSH container."""

    from tests.storage.contract import StorageContractTests

    for _name, _method in vars(StorageContractTests).items():
        if _name.startswith("test_"):
            locals()[_name] = _method


class TestSFTPSpecific:
    """SFTP-specific tests beyond the contract."""

    def test_get_modified_time(self, adapter):
        from datetime import datetime

        name = "mtime_dir/sftp_mtime_test.txt"
        adapter.save(name, b"mtime")

        mtime = adapter.get_modified_time(name)
        assert isinstance(mtime, datetime)

        adapter.delete(name)
