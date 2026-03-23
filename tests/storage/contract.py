"""
Storage port contract test suite.

Provides a reusable base class that any StoragePort adapter must pass.
Subclass StorageContractTests, implement the `adapter` fixture, and all
contract tests run automatically.

Usage:
    class TestMyStorageAdapter(StorageContractTests):
        @pytest.fixture
        def adapter(self):
            return MyStorageAdapter(credentials={...})
"""

from __future__ import annotations

import uuid
from io import BytesIO

import pytest

from bapp_connectors.core.ports import StoragePort


def _unique_name(prefix: str = "test", ext: str = "txt") -> str:
    """Generate a unique file name to avoid collisions between test runs."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}.{ext}"


class StorageContractTests:
    """
    Contract tests for StoragePort implementations.

    Every storage adapter must pass these. They verify the Django Storage API
    contract: save → exists → open/download → size → listdir → delete → !exists.

    Subclasses MUST provide an `adapter` fixture that returns a connected
    StoragePort instance, and a `test_dir` fixture for the remote directory.
    """

    @pytest.fixture
    def adapter(self) -> StoragePort:
        """Override in subclass to provide a connected adapter."""
        raise NotImplementedError

    @pytest.fixture
    def test_dir(self) -> str:
        """Remote directory for test files. Override if needed.

        Uses a relative path so the adapter's default_folder is applied.
        """
        return f"bapp_test_{uuid.uuid4().hex[:8]}"

    # ── Connection ──

    def test_validate_credentials(self, adapter: StoragePort):
        assert adapter.validate_credentials() is True

    def test_test_connection(self, adapter: StoragePort):
        result = adapter.test_connection()
        assert result.success is True, f"Connection failed: {result.message}"

    # ── Save & Exists ──

    def test_save_and_exists(self, adapter: StoragePort, test_dir: str):
        name = f"{test_dir}/{_unique_name()}"
        content = b"hello world"

        returned_name = adapter.save(name, content)
        assert returned_name  # should return something

        assert adapter.exists(name) is True

        # Cleanup
        adapter.delete(name)

    def test_exists_returns_false_for_missing(self, adapter: StoragePort, test_dir: str):
        assert adapter.exists(f"{test_dir}/nonexistent_{uuid.uuid4().hex}.txt") is False

    # ── Save with file-like object ──

    def test_save_file_object(self, adapter: StoragePort, test_dir: str):
        name = f"{test_dir}/{_unique_name()}"
        content = BytesIO(b"file object content")

        adapter.save(name, content)
        assert adapter.exists(name) is True

        adapter.delete(name)

    # ── Open / Download ──

    def test_open_returns_content(self, adapter: StoragePort, test_dir: str):
        name = f"{test_dir}/{_unique_name()}"
        content = b"read me back"

        adapter.save(name, content)

        f = adapter.open(name)
        try:
            data = f.read()
            assert data == content
        finally:
            f.close()

        adapter.delete(name)

    def test_download_returns_bytes(self, adapter: StoragePort, test_dir: str):
        name = f"{test_dir}/{_unique_name()}"
        content = b"download test"

        adapter.save(name, content)
        data = adapter.download(name)
        assert data == content

        adapter.delete(name)

    # ── Size ──

    def test_size(self, adapter: StoragePort, test_dir: str):
        name = f"{test_dir}/{_unique_name()}"
        content = b"x" * 42

        adapter.save(name, content)
        assert adapter.size(name) == 42

        adapter.delete(name)

    # ── Delete ──

    def test_delete(self, adapter: StoragePort, test_dir: str):
        name = f"{test_dir}/{_unique_name()}"
        adapter.save(name, b"to be deleted")
        assert adapter.exists(name) is True

        adapter.delete(name)
        assert adapter.exists(name) is False

    def test_delete_nonexistent_does_not_raise(self, adapter: StoragePort, test_dir: str):
        # Django contract: delete() should not raise if file doesn't exist
        adapter.delete(f"{test_dir}/nonexistent_{uuid.uuid4().hex}.txt")

    # ── Listdir ──

    def test_listdir(self, adapter: StoragePort, test_dir: str):
        file1 = f"{test_dir}/{_unique_name('a')}"
        file2 = f"{test_dir}/{_unique_name('b')}"

        adapter.save(file1, b"file1")
        adapter.save(file2, b"file2")

        dirs, files = adapter.listdir(test_dir)
        # files list should contain at least our 2 files
        assert len(files) >= 2, f"Expected at least 2 files, got {files}"

        adapter.delete(file1)
        adapter.delete(file2)

    # ── Upload / convenience wrapper ──

    def test_upload_convenience(self, adapter: StoragePort, test_dir: str):
        file_name = _unique_name("upload")
        adapter.upload(b"via upload()", file_name, test_dir)

        # Should be retrievable
        data = adapter.download(f"{test_dir}/{file_name}")
        assert data == b"via upload()"

        adapter.delete(f"{test_dir}/{file_name}")

    # ── List files (FileInfo) ──

    def test_list_files(self, adapter: StoragePort, test_dir: str):
        name = f"{test_dir}/{_unique_name('info')}"
        adapter.save(name, b"metadata test")

        entries = adapter.list_files(test_dir)
        assert len(entries) >= 1
        names = [e.name for e in entries]
        file_name = name.rsplit("/", 1)[-1]
        assert file_name in names, f"Expected {file_name} in {names}"

        adapter.delete(name)

    # ── Binary content ──

    def test_binary_content(self, adapter: StoragePort, test_dir: str):
        name = f"{test_dir}/{_unique_name('bin', 'dat')}"
        content = bytes(range(256))  # all byte values 0x00-0xFF

        adapter.save(name, content)
        data = adapter.download(name)
        assert data == content

        adapter.delete(name)

    # ── Overwrite ──

    def test_overwrite(self, adapter: StoragePort, test_dir: str):
        name = f"{test_dir}/{_unique_name('overwrite')}"

        adapter.save(name, b"version 1")
        adapter.save(name, b"version 2")

        data = adapter.download(name)
        assert data == b"version 2"

        adapter.delete(name)
