"""
WebDAV storage integration tests — runs against bytemark/webdav in Docker.

Requires:
    docker compose -f docker-compose.test.yml up -d
    uv run --extra dev pytest tests/storage/test_webdav.py -v -m integration
"""

from __future__ import annotations

import pytest

from tests.storage.conftest import WEBDAV_HOST, WEBDAV_PORT, skip_unless_webdav

pytestmark = [pytest.mark.integration, skip_unless_webdav]


@pytest.fixture
def adapter():
    from bapp_connectors.providers.storage.webdav.adapter import WebDAVStorageAdapter

    return WebDAVStorageAdapter(
        credentials={
            "username": "testuser",
            "password": "testpass",
            "base_url": f"http://{WEBDAV_HOST}:{WEBDAV_PORT}",
        },
        config={
            "default_folder": "/",
            "verify_ssl": False,
            "timeout": 10,
        },
    )


class TestWebDAVContract:
    """Run the full storage contract suite against WebDAV server."""

    from tests.storage.contract import StorageContractTests

    for _name, _method in vars(StorageContractTests).items():
        if _name.startswith("test_"):
            locals()[_name] = _method
