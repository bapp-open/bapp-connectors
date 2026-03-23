"""
FTP storage integration tests — runs against vsftpd in Docker.

Requires:
    docker compose -f docker-compose.test.yml up -d
    uv run --extra dev pytest tests/storage/test_ftp.py -v -m integration
"""

from __future__ import annotations

import pytest

from tests.storage.conftest import FTP_HOST, FTP_PORT, skip_unless_ftp

pytestmark = [pytest.mark.integration, skip_unless_ftp]


@pytest.fixture
def adapter():
    from bapp_connectors.providers.storage.ftp.adapter import FTPStorageAdapter

    return FTPStorageAdapter(
        credentials={
            "host": FTP_HOST,
            "port": str(FTP_PORT),
            "username": "testuser",
            "password": "testpass",
            "default_folder": "",
        },
    )


class TestFTPContract:
    """Run the full storage contract suite against vsftpd."""

    from tests.storage.contract import StorageContractTests

    for _name, _method in vars(StorageContractTests).items():
        if _name.startswith("test_"):
            locals()[_name] = _method
