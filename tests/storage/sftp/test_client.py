"""
SFTP client unit tests — no server, no Docker, always run.

Covers the two things `SFTPClient` gained beyond "it talks SFTP": a `timeout` that is
actually applied to the socket, and a byte ceiling on `download`.
"""

from __future__ import annotations

import socket
from unittest import mock

import pytest

paramiko = pytest.importorskip(
    "paramiko", reason="SFTP needs the [sftp] extra", exc_type=ImportError
)

from bapp_connectors.providers.storage.errors import FileTooLargeError  # noqa: E402
from bapp_connectors.providers.storage.sftp.client import SFTPClient  # noqa: E402


class FakeAttrs:
    def __init__(self, size: int):
        self.st_size = size
        self.st_mtime = 1_700_000_000
        self.st_mode = 0o100644


class FakeSFTP:
    """Enough of a `paramiko.SFTPClient` to answer a stat and a getfo in chunks."""

    def __init__(self, content: bytes = b"", chunk: int = 1000, stated_size: int | None = None):
        self.content = content
        self.chunk = chunk
        self.stated_size = len(content) if stated_size is None else stated_size
        self.stated: list[str] = []
        self.fetched: list[str] = []
        self.delivered = 0
        self.closed = False

    def stat(self, path):
        self.stated.append(path)
        return FakeAttrs(self.stated_size)

    def getfo(self, path, sink):
        self.fetched.append(path)
        for start in range(0, len(self.content), self.chunk):
            piece = self.content[start:start + self.chunk]
            self.delivered += len(piece)
            sink.write(piece)
        return self.delivered

    def close(self):
        self.closed = True


def client_with(fake: FakeSFTP, **kwargs) -> SFTPClient:
    client = SFTPClient(host="gazda.test", username="u", password="p", **kwargs)
    transport = mock.Mock(name="transport")
    client._open_sftp = lambda: (transport, fake)  # type: ignore[method-assign]
    return client


# ── the byte ceiling ──

def test_without_a_ceiling_the_whole_body_comes_back():
    fake = FakeSFTP(content=b"x" * 5000)
    assert client_with(fake).download("/export/stoc.csv") == b"x" * 5000
    assert fake.stated == [], "fara plafon nu are ce cauta un stat"


def test_a_body_under_the_ceiling_comes_back_whole():
    fake = FakeSFTP(content=b"x" * 900)
    assert client_with(fake).download("/export/stoc.csv", max_bytes=1000) == b"x" * 900


def test_a_file_the_server_admits_is_too_big_is_refused_before_it_is_fetched():
    """Unlike FTP, SFTP can be asked the size first — so the usual refusal costs one
    round trip instead of a transfer."""
    fake = FakeSFTP(content=b"x" * 5000)
    with pytest.raises(FileTooLargeError) as caught:
        client_with(fake).download("/export/stoc.csv", max_bytes=2000)
    assert fake.stated == ["/export/stoc.csv"]
    assert fake.fetched == [], "nu s-a descarcat degeaba"
    assert caught.value.size == 5000
    assert caught.value.max_bytes == 2000
    assert caught.value.retryable is False


def test_a_file_that_lies_about_its_size_is_still_stopped_mid_transfer():
    """The stat is the cheap path, not the guard: a file can grow between the stat and
    the read, and a server is free to misreport."""
    fake = FakeSFTP(content=b"x" * 100_000, chunk=1000, stated_size=10)
    with pytest.raises(FileTooLargeError) as caught:
        client_with(fake).download("/export/stoc.csv", max_bytes=3000)
    assert fake.delivered < 100_000, "transferul a mers pana la capat degeaba"
    assert fake.delivered <= 3000 + fake.chunk
    assert caught.value.size is None


def test_the_ceiling_is_exact_to_the_byte():
    assert len(client_with(FakeSFTP(content=b"x" * 1000)).download("/f.csv", max_bytes=1000)) == 1000
    with pytest.raises(FileTooLargeError):
        client_with(FakeSFTP(content=b"x" * 1001)).download("/f.csv", max_bytes=1000)


def test_the_ceiling_survives_the_default_folder():
    fake = FakeSFTP(content=b"x" * 100)
    client_with(fake, default_folder="/upload").download("stoc.csv", max_bytes=1000)
    assert fake.stated == ["/upload/stoc.csv"]
    assert fake.fetched == ["/upload/stoc.csv"]


# ── the timeout ──

def test_the_socket_is_opened_with_our_timeout_not_left_to_the_operating_system():
    """`paramiko.Transport((host, port))` calls `sock.connect()` with no timeout at
    all, so a host that swallows packets used to hold the caller for as long as the
    system's TCP timeout."""
    transport = mock.Mock(name="transport")
    with mock.patch.object(socket, "create_connection") as create, \
         mock.patch.object(paramiko, "Transport", return_value=transport) as build:
        client = SFTPClient(host="gazda.test", port=2222, username="u", password="p", timeout=42)
        assert client._connect_transport() is transport

    create.assert_called_once_with(("gazda.test", 2222), timeout=42)
    build.assert_called_once_with(create.return_value)
    # paramiko replaces the socket timeout with its own poll interval as soon as it
    # takes the socket, so the later phases need bounds of their own.
    assert transport.banner_timeout == 42
    assert transport.auth_timeout == 42
    transport.connect.assert_called_once_with(username="u", password="p", pkey=None)


def test_a_socket_that_never_becomes_a_transport_is_not_leaked():
    with mock.patch.object(socket, "create_connection") as create, \
         mock.patch.object(paramiko, "Transport", side_effect=OSError("boom")), pytest.raises(OSError, match="boom"):
        SFTPClient(host="gazda.test", username="u", password="p")._connect_transport()
    create.return_value.close.assert_called_once()


def test_a_transport_that_fails_to_authenticate_is_closed():
    transport = mock.Mock(name="transport")
    transport.connect.side_effect = paramiko.AuthenticationException("no")
    with (
        mock.patch.object(socket, "create_connection"),
        mock.patch.object(paramiko, "Transport", return_value=transport),
        pytest.raises(paramiko.AuthenticationException),
    ):
        SFTPClient(host="gazda.test", username="u", password="p")._connect_transport()
    transport.close.assert_called_once()


def test_an_unreadable_private_key_is_refused_before_a_socket_is_opened():
    with mock.patch.object(socket, "create_connection") as create, pytest.raises(ValueError, match="private key"):
        SFTPClient(host="gazda.test", username="u", private_key="nu e o cheie")._connect_transport()
    create.assert_not_called()


def test_a_server_that_refuses_the_sftp_subsystem_does_not_leak_the_transport():
    transport = mock.Mock(name="transport")
    client = SFTPClient(host="gazda.test", username="u", password="p")
    client._connect_transport = lambda: transport  # type: ignore[method-assign]
    with (
        mock.patch.object(paramiko.SFTPClient, "from_transport", return_value=None),
        pytest.raises(paramiko.SSHException),
    ):
        client._open_sftp()
    transport.close.assert_called_once()


# ── one handshake for a size check and the download it guards ──

def test_the_session_can_stat_so_a_check_and_its_download_share_a_connection():
    fake = FakeSFTP(content=b"x" * 100)
    client = SFTPClient(host="gazda.test", username="u", password="p", default_folder="/upload")
    transport = mock.Mock(name="transport")
    with mock.patch.object(client, "_open_sftp", return_value=(transport, fake)), client.connect() as session:
        assert session.stat("stoc.csv") == {
            "size": 100,
            "modified_at": 1_700_000_000,
            "is_directory": False,
        }
        assert session.download("stoc.csv", max_bytes=1000) == b"x" * 100

    assert fake.fetched == ["/upload/stoc.csv"]
    assert transport.close.call_count == 1, "un singur handshake, nu doua"
