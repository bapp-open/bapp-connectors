"""
FTP client unit tests — no server, no Docker, always run.

Covers the two things `FTPClient` gained beyond "it talks FTP": the byte ceiling on
`download_file`, and a connection that is dropped rather than politely closed when an
operation fails.
"""

from __future__ import annotations

import ftplib
from unittest import mock

import pytest

from bapp_connectors.providers.storage.errors import FileTooLargeError
from bapp_connectors.providers.storage.ftp.client import FTPClient


class FakeFTP:
    """Enough of an `ftplib.FTP` to answer a RETR in chunks and record its goodbye."""

    def __init__(self, content: bytes = b"", chunk: int = 1000, on_command=None):
        self.content = content
        self.chunk = chunk
        self.on_command = on_command
        self.commands: list[str] = []
        self.delivered = 0
        self.quit_called = False
        self.close_called = False

    def retrbinary(self, command, callback, blocksize=8192):
        self.commands.append(command)
        for start in range(0, len(self.content), self.chunk):
            piece = self.content[start:start + self.chunk]
            self.delivered += len(piece)
            callback(piece)
        return "226 Transfer complete."

    def voidcmd(self, command):
        self.commands.append(command)
        if self.on_command:
            self.on_command(command)
        return "200 OK"

    def quit(self):
        self.quit_called = True

    def close(self):
        self.close_called = True


def client_with(fake: FakeFTP) -> FTPClient:
    client = FTPClient(host="gazda.test", username="u", password="p")
    client._connect = lambda: fake  # type: ignore[method-assign]
    return client


# ── the byte ceiling ──

def test_without_a_ceiling_the_whole_body_comes_back():
    fake = FakeFTP(content=b"x" * 5000)
    assert client_with(fake).download_file("/export/stoc.csv") == b"x" * 5000
    assert fake.commands == ["RETR /export/stoc.csv"]


def test_a_body_under_the_ceiling_comes_back_whole():
    fake = FakeFTP(content=b"x" * 900)
    assert client_with(fake).download_file("/export/stoc.csv", max_bytes=1000) == b"x" * 900


def test_a_body_over_the_ceiling_is_refused():
    fake = FakeFTP(content=b"x" * 5000, chunk=1000)
    with pytest.raises(FileTooLargeError) as caught:
        client_with(fake).download_file("/export/stoc.csv", max_bytes=2000)
    assert caught.value.max_bytes == 2000
    assert caught.value.retryable is False


def test_the_ceiling_stops_the_transfer_instead_of_judging_it_at_the_end():
    """The point of the cap is the memory never held, not the error at the end."""
    fake = FakeFTP(content=b"x" * 100_000, chunk=1000)
    with pytest.raises(FileTooLargeError):
        client_with(fake).download_file("/export/stoc.csv", max_bytes=3000)
    assert fake.delivered < 100_000, "transferul a mers pana la capat degeaba"
    assert fake.delivered <= 3000 + fake.chunk


def test_the_ceiling_is_exact_to_the_byte():
    fake = FakeFTP(content=b"x" * 1000, chunk=1)
    assert len(client_with(fake).download_file("/f.csv", max_bytes=1000)) == 1000
    with pytest.raises(FileTooLargeError):
        client_with(FakeFTP(content=b"x" * 1001, chunk=1)).download_file("/f.csv", max_bytes=1000)


# ── how the connection is let go ──

def test_a_finished_download_says_goodbye():
    fake = FakeFTP(content=b"ok")
    client_with(fake).download_file("/f.csv")
    assert fake.quit_called and not fake.close_called


def test_a_failed_download_drops_the_socket_instead_of_waiting_for_a_goodbye():
    """`quit()` waits for the server to answer; on the error path nobody may be left
    to answer, and that wait burns the whole timeout again before the real error
    surfaces."""
    fake = FakeFTP(content=b"x" * 5000, chunk=1000)
    with pytest.raises(FileTooLargeError):
        client_with(fake).download_file("/f.csv", max_bytes=2000)
    assert fake.close_called and not fake.quit_called


def test_a_failed_auth_check_does_not_leak_the_connection():
    """`test_auth` used to return False with the connection still open."""

    def blow_up(command):
        raise OSError("connection reset")

    fake = FakeFTP(on_command=blow_up)
    assert client_with(fake).test_auth() is False
    assert fake.close_called


def test_a_passing_auth_check_says_goodbye():
    fake = FakeFTP()
    assert client_with(fake).test_auth() is True
    assert fake.commands == ["NOOP"]
    assert fake.quit_called and not fake.close_called


# ── the timeout the library already honoured ──

def test_the_timeout_reaches_ftplib_and_is_not_its_default():
    with mock.patch("bapp_connectors.providers.storage.ftp.client.FTP") as ftp:
        FTPClient(host="gazda.test", username="u", password="p", timeout=90)._connect()
    ftp.assert_called_once_with(timeout=90)


def test_tls_uses_ftp_tls_and_protects_the_data_channel():
    """A real subclass, not a Mock: `_connect` guards `prot_p()` with an `isinstance`."""
    calls = []

    class StubFTPTLS(ftplib.FTP_TLS):
        def __init__(self, timeout=None):
            calls.append(("init", timeout))

        def connect(self, host="", port=0, timeout=None, source_address=None):
            calls.append(("connect", host, port))

        def login(self, user="", passwd="", acct="", secure=True):
            calls.append(("login", user))

        def prot_p(self):
            calls.append(("prot_p",))

    with mock.patch("bapp_connectors.providers.storage.ftp.client.FTP_TLS", StubFTPTLS):
        FTPClient(host="gazda.test", port=990, username="u", password="p", use_tls=True, timeout=90)._connect()

    assert calls == [("init", 90), ("connect", "gazda.test", 990), ("login", "u"), ("prot_p",)]
