"""
S3 storage integration tests — runs against MinIO in Docker.

Requires:
    docker compose -f docker-compose.test.yml up -d
    uv run --extra dev --extra s3 pytest tests/storage/test_s3.py -v -m integration
"""

from __future__ import annotations

import pytest

from tests.storage.conftest import MINIO_HOST, MINIO_PORT, skip_unless_minio

pytestmark = [pytest.mark.integration, skip_unless_minio]


@pytest.fixture
def adapter():
    from bapp_connectors.providers.storage.s3.adapter import S3StorageAdapter

    return S3StorageAdapter(
        credentials={
            "access_key_id": "minioadmin",
            "secret_access_key": "minioadmin",
            "bucket": "test-bucket",
        },
        config={
            "endpoint_url": f"http://{MINIO_HOST}:{MINIO_PORT}",
            "region": "us-east-1",
            "addressing_style": "path",
        },
    )


class TestS3Contract:
    """Run the full storage contract suite against MinIO."""

    from tests.storage.contract import StorageContractTests

    # Inherit all contract tests
    for _name, _method in vars(StorageContractTests).items():
        if _name.startswith("test_"):
            locals()[_name] = _method


class TestS3Specific:
    """S3-specific tests beyond the contract."""

    def test_url_generation(self, adapter):
        url = adapter.url("reports/2024/q1.pdf")
        assert "test-bucket" in url
        assert "reports/2024/q1.pdf" in url

    def test_get_modified_time(self, adapter):
        from datetime import datetime

        name = "s3_test_mtime.txt"
        adapter.save(name, b"mtime test")

        mtime = adapter.get_modified_time(name)
        assert isinstance(mtime, datetime)

        adapter.delete(name)
